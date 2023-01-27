import json
import os
from datetime import datetime

import openai
import telebot
from decouple import config
from telebot import types
import glob

bot = telebot.TeleBot(config('TB_TOKEN'))
openai.api_key = config('OAI_TOKEN')
password = config('PASSWORD')

# Vocabulary for storing conversation contexts and parameters
cfg = {
    'default': {
        'context': [],
        'authorised': False,
        'with_context': True,
        'html_log': False,
        'auto_slice': ':4',
        'max_tokens': int(config('MAX_TOKENS')),
        'temperature': float(config('TEMPERATURE')),
        'engine': config('ENGINE')
    },
}

work_dir = os.getcwdb().decode("utf-8")


def cfg_save():
    fn = os.path.join(work_dir, 'cfg.json')
    with open(fn, 'w') as fp:
        json.dump(cfg, fp, indent=4)


def cfg_load():
    global cfg
    fn = os.path.join(work_dir, 'cfg.json')
    if os.path.exists(fn):
        with open(fn, 'r') as fp:
            cfg = json.load(fp)
    else:
        cfg_save()


cfg_load()


def bot_send(chat_id, mes):
    keyboard = types.ReplyKeyboardMarkup(True, True)
    if chat_id not in cfg or not cfg[chat_id]['with_context']:
        keyboard.row('/start', '/context on', '/params')
    else:
        keyboard.row('/start', '/context', '/context to_send', '/params')
        keyboard.row('/context off', '/context clear', '/context load', '/context save')
        keyboard.row('/context items', '/context slice', '/context to_file', '/context from_file')
    bot.send_message(chat_id, mes, reply_markup=keyboard)


def bot_ask_pswd(chat_id):
    if chat_id not in cfg or not cfg[chat_id]['authorised']:
        bot_send(chat_id, 'Input password')


# Password handler
@bot.message_handler(func=lambda message: message.text == password)
def start_conversation(message):
    chat_id = str(message.chat.id)
    cfg[chat_id] = cfg['default'].copy()
    cfg[chat_id]['authorised'] = True
    cfg_save()
    bot_send(chat_id, "You entered the correct password! Write me something to start a dialogue.")


# Handler for command /start
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = str(message.chat.id)
    cfg_load()
    bot_send(chat_id,
             'Hi! I am a bot to help you get the right answers to your questions. Type in your question and I will '
             'try to find a suitable answer.')


def slice_from_str(s):
    return slice(*[{True: lambda n: None, False: int}[x == ''](x) for x in (s.split(':') + ['', '', ''])[:3]])


def bot_send_4000(chat_id, s):
    if len(s) > 4000:
        bot_send(chat_id, s[:4000] + '\n...')
    else:
        bot_send(chat_id, s)


# Handler for command /context
@bot.message_handler(commands=['context'])
def context_h(message):
    chat_id = str(message.chat.id)
    if chat_id not in cfg or not cfg[chat_id]['authorised']:
        bot_ask_pswd(chat_id)
        return
    args = extract_arg(message.text)
    if len(args) == 0:
        if chat_id in cfg and len(cfg[chat_id]['context']) > 0:
            bot_send_4000(chat_id, '\n\n'.join(cfg[chat_id]['context']))
        else:
            bot_send(chat_id, 'Context is Empty')
        return
    match args[0]:
        case 'to_send':
            bot_send_4000(chat_id, '\n\n'.join(cfg[chat_id]['context'][slice_from_str(cfg[chat_id]['auto_slice'])]))
        case 'clear':
            cfg[chat_id]['context'] = []
            bot_send(chat_id, 'Context was cleared and saved.')
        case 'on':
            cfg[chat_id]['with_context'] = True
            bot_send(chat_id, 'The new query will extend the previous one.\n '
                              'You can modify context be "/context [smth]" commands.')
        case 'off':
            cfg[chat_id]['with_context'] = False
            bot_send(chat_id, 'Each request now goes by itself.')
        case 'items':
            if len(args) == 1:
                if len(cfg[chat_id]['context']) > 0:
                    i = 0
                    res = ""
                    for s in cfg[chat_id]['context']:
                        i += 1
                        res += str(i) + ") " + s.strip("\n").split("\n")[0][:40] + "...\n"
                    bot_send(chat_id, res)
            else:
                bot_send(chat_id, 'Context is Empty')
        case 'load':
            cfg_load()
            bot_send_4000(chat_id, '\n\n'.join(cfg[chat_id]['context']))
        case 'save':
            cfg_save()
            bot_send(chat_id, 'Context saved.')
        case 'from_file':
            root_dir = os.path.join(work_dir, f'{chat_id}')
            if len(args) == 1:
                res = 'Execute "/context from_file N"\nwhere N get from the following list:\n\n'
                i = 0
                for path in glob.glob('*.json', root_dir=root_dir):
                    i += 1
                    res += f'{i}) {path}\n'
                bot_send(chat_id, res)
            else:
                i = 0
                for fn in glob.glob('*.json', root_dir=root_dir):
                    i += 1
                    if i == int(args[1]):
                        with open(os.path.join(root_dir, fn), 'r') as fp:
                            cfg[chat_id]['context'] = json.load(fp)
                        bot_send_4000(chat_id, '\n\n'.join(cfg[chat_id]['context']))
                        break
        case 'to_file':
            tmp = cfg[chat_id]['context'].copy()
            if chat_id in cfg and len(tmp) > 0:
                dir_name = os.path.join(work_dir, f'{chat_id}')
                if not os.path.exists(dir_name):
                    os.makedirs(dir_name)
                if len(args) > 1:
                    fn = os.path.join(dir_name, args[1] + '.txt')
                    with open(fn, 'w', encoding='utf-8') as f:
                        f.write('\n\n'.join(tmp))
                else:
                    tmp.append(f'\nPropose file name without extension for this dialogue.\n')
                    prompt = '\n\n'.join(tmp)
                    response = send_to_openai(prompt)
                    fn = response.choices[0].text.strip("\n")
                    fn += datetime.now().strftime("_%Y%m%d_%H%M%S")
                    fn += '.json'
                    fn = os.path.join(dir_name, fn)
                    with open(fn, 'w') as f:
                        json.dump(cfg[chat_id]['context'], f, indent=4)
                bot_send(chat_id, f'Saved to {fn}')
            else:
                bot_send(chat_id, 'Nothing to save')
        case 'slice':
            if len(args) == 1:
                bot_send(chat_id, 'Examples:\n '
                                  '"/context slice :4" - keep only first 4 items\n'
                                  '"/context slice -5:" - keep only last 5 items\n'
                                  '"/context slice ::2" - keep only requests\n'
                                  '"/context slice 1::2" - keep only responses\n')
            else:
                cfg[chat_id]['context'] = cfg[chat_id]['context'][slice_from_str(args[1])]
                bot_send_4000(chat_id, '\n\n'.join(cfg[chat_id]['context']))


def extract_arg(arg):
    return arg.split()[1:]


@bot.message_handler(commands=['params'])
def params(message):
    chat_id = str(message.chat.id)
    if chat_id not in cfg or not cfg[chat_id]['authorised']:
        bot_ask_pswd(chat_id)
        return
    args = extract_arg(message.text)
    if len(args) == 0:
        bot_send(chat_id,
                 f"/params max_tokens={cfg[chat_id]['max_tokens']} temperature={cfg[chat_id]['temperature']} "
                 f"engine={cfg[chat_id]['engine']} html_log={cfg[chat_id]['html_log']} "
                 f"auto_slice={cfg[chat_id]['auto_slice']}")
        return
    for arg in args:
        x = arg.split('=')
        if x[0] == 'max_tokens':
            cfg[chat_id]['max_tokens'] = int(x[1])
            bot_send(chat_id, f'max_tokens = {x[1]}')
            continue
        if x[0] == 'temperature':
            cfg[chat_id]['temperature'] = float(x[1])
            bot_send(chat_id, f'temperature = {x[1]}')
            continue
        if x[0] == 'engine':
            cfg[chat_id]['engine'] = x[1]
            bot_send(chat_id, f'engine = {x[1]}')
            continue
        if x[0] == 'auto_slice':
            cfg[chat_id]['auto_slice'] = x[1]
            bot_send(chat_id, f'auto_slice = {x[1]}')
            continue
        if x[0] == 'html_log':
            cfg[chat_id]['html_log'] = x[1] == '1' or x[1] == 'true' or x[1] == 'True'
            bot_send(chat_id, f"html_log = {cfg[chat_id]['html_log']}")
            continue
    cfg_save()


# Send a request to OpenAI
def send_to_openai(prompt, engine="text-davinci-003", max_tokens="3000", temperature="0.7"):
    return openai.Completion.create(
        engine=engine,
        prompt=prompt,
        max_tokens=int(max_tokens),
        n=1,
        stop=None,
        temperature=float(temperature),
    )


# Function for processing incoming messages and constructing a dialog context
@bot.message_handler(func=lambda message: True)
def dialog(message):
    chat_id = str(message.chat.id)
    if chat_id not in cfg or not cfg[chat_id]['authorised']:
        bot_ask_pswd(chat_id)
        return
    if not cfg[chat_id]['with_context']:
        prompt = message.text
    else:
        if len(cfg[chat_id]['auto_slice']) > 0:
            temp = cfg[chat_id]['context'].copy()
            temp = temp[slice_from_str(cfg[chat_id]['auto_slice'])]
            temp.append('\n' + message.text.strip("\n"))
            prompt = '\n\n'.join(temp)
            cfg[chat_id]['context'].append('\n' + message.text.strip("\n"))
        else:
            cfg[chat_id]['context'].append('\n' + message.text.strip("\n"))
            prompt = '\n\n'.join(cfg[chat_id]['context'])
    print(message.text)
    print()
    response = send_to_openai(prompt,
                              cfg[chat_id]['engine'],
                              cfg[chat_id]['max_tokens'],
                              cfg[chat_id]['temperature'])
    if cfg[chat_id]['with_context']:
        cfg[chat_id]['context'].append(response.choices[0].text.strip("\n"))
    cfg_save()
    if cfg[chat_id]['html_log']:
        dir_name = os.path.join(work_dir, f'{chat_id}')
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)
        with open(dir_name + '/' + datetime.now().strftime("%Y-%m-%d") + '.html', 'a', encoding='utf-8') as f:
            f.write(
                f'<div style="margin:15px;padding:15px;width:600px;overflow:auto;white-space:pre-wrap;'
                f'border-style:double;">\n')
            f.write(f'<h4>{prompt}</h4>\n')
            f.write(f'<pre style="white-space:pre-wrap;">\n{response.choices[0].text}\n</pre>\n</div>\n\n')
    bot_send(chat_id, response.choices[0].text)


while True:
    try:
        bot.polling()
    except Exception as err:
        print(f"Unexpected {err=}, {type(err)=}")
