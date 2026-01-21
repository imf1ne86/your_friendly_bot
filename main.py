"""
* ПО "Твой дружелюбный бот"
* *************************
* Программа является ботом для сервиса "Telegram".
* Для работы программы требуется Python 3. Предварительно
* требуется установить необходимые библиотеки:
* $ pip3 install --trusted-host pypi.org --trusted-host files.pythonhosted.org --upgrade pip
* $ pip3 install --trusted-host pypi.org --trusted-host files.pythonhosted.org configparser
* $ pip3 install --trusted-host pypi.org --trusted-host files.pythonhosted.org psutil
* Программа является кроссплатформенной. Она должна работать
* под Microsoft Windows, Linux, macOS и т.д.
*
* @author Ефремов А. В., 30.06.2025
"""

import logging, sys
import os
import configparser
import argparse
import time, threading
import shlex
import random

import sqlite3
from sqlite3 import IntegrityError, OperationalError, Error

from requests.exceptions import ProxyError
from telebot.apihelper import ApiTelegramException
from requests.exceptions import ReadTimeout

import telebot
from telebot import apihelper
from telebot.types import Message

from miscellaneous import Miscellaneous
from downgrade import Downgrade
from models import Constant
from ircbot import IRCBot
from irc.client import ServerNotConnectedError
from chatscript import ChatScript

MSG_NUMBER_LIMIT: int = 15 # лимит на количество одновременных сообщений от бота к пользователю
LOG_FILE: str = f"{__name__}.log" # имя файла для ведения лога
cnt: int = 0

debugged: bool = False # режим отладки (по умолчанию отключён)

is_irc_bot_running = False # признак работы IRC-бота
irc_bot: IRCBot = None

is_chatscript_bot_running = False # признак работы ChatScript-бота
oChatScript: ChatScript = None

class LoggerWriter:
    """
    * Класс, который перехватывает вывод в stdout/stderr
    * и перенаправляет его в лог
    """

    def __init__(self, logger, level, original_stream):
        self.logger = logger
        self.level = level
        self.original_stream = original_stream  # сохраняем ссылку на исходный поток

    def write(self, message):
        """
        * Запись сообщения в лог
        """
        self.original_stream.write(message)  # выводим в исходный поток (консоль)
        if message.rstrip() != "":  # Избегаем пустых строк
            self.logger.log(self.level, message.rstrip())

    def flush(self):
        """
        * Очистка буфера
        * (не требуется, но рекомендуется реализовать)
        """
        self.original_stream.flush()  # очищаем и исходный поток

def get_bot_config():
    """
    * Получение конфигурации для бота
    *
    * @return token, http_proxy, https_proxy
    """
    global LOG_FILE
    global debugged
    GLOBAL_SECTION: str = "global"
    PROXY_SECTION: str = "proxy"
    NO_PROXY: str = "DIRECT"
    TOKEN: str = "api_token"
    HTTP_PROXY: str = "http"
    HTTPS_PROXY: str = "https"
    DEBUG: str = "debug"
    config = configparser.ConfigParser()
    try:
        with open(Constant.SETTINGS_FILE.value, 'r', encoding=Constant.GLOBAL_CODEPAGE.value) as f:
            config.read_file(f)
            if debugged == False: # включали и настраивали уже отладку?
                if GLOBAL_SECTION in config and DEBUG in config[GLOBAL_SECTION]:
                    debugged = (config[GLOBAL_SECTION][DEBUG].upper().strip() == "Y")
                if ( # проверка, что файл лога доступен для записи
                    (debugged == True)
                    and (os.path.exists(LOG_FILE))
                    and (os.path.isfile(LOG_FILE))
                    and (not os.access(LOG_FILE, os.W_OK))
                ):
                    debugged = False
                if debugged == True:
                    Miscellaneous.print_message("Отладка включена.")
                    logging.basicConfig(
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        filename=LOG_FILE, # логирование в файл
                        level=logging.INFO
                    )
                    logger = logging.getLogger(__name__)
                    # Перенаправление stdout и stderr
                    sys.stdout = LoggerWriter(logger, logging.INFO, sys.stdout)  # перехватываем print
                    sys.stderr = LoggerWriter(logger, logging.ERROR, sys.stderr)  # перехватываем ошибки
                else:
                    Miscellaneous.print_message("Отладка выключена.")
            if GLOBAL_SECTION in config and TOKEN in config[GLOBAL_SECTION]:
                v_token: str = config[GLOBAL_SECTION][TOKEN].strip()
            if PROXY_SECTION in config and HTTP_PROXY in config[PROXY_SECTION]:
                v_http_proxy: str = config[PROXY_SECTION][HTTP_PROXY].strip()
                if v_http_proxy.upper() == NO_PROXY:
                    v_http_proxy = ""
            if PROXY_SECTION in config and HTTPS_PROXY in config[PROXY_SECTION]:
                v_https_proxy: str = config[PROXY_SECTION][HTTPS_PROXY].strip()
                if v_https_proxy.upper() == NO_PROXY:
                    v_https_proxy = ""
            if "".__eq__(v_token):
                return None, None, None
            else:
                return v_token, v_http_proxy, v_https_proxy
    except FileNotFoundError:
        Miscellaneous.print_message(f"Ошибка: Файл настроек не найден: {Constant.SETTINGS_FILE.value}")
        return None, None, None
    except Exception as e:
        Miscellaneous.print_message(f"Ошибка при чтении файла настроек: {e}")
        return None, None, None

def send_message(bot: telebot, chat_id: int, msg: str) -> None:
    """
    * Отправка сообщения для пользователя в Telegram
    *
    * @param bot Экземпляр бота
    * @param chat_id Уникальный идентификатор пользователя в Telegram
    * @param msg Текст сообщения
    """
    if not "".__eq__(msg):
        reply_msg: Message = bot.send_message(chat_id, msg)
        if reply_msg is not None and not "".__eq__(reply_msg.text):
            Miscellaneous.print_message(f"Ответ пользователю {chat_id}: {chr(34)}{reply_msg.text}{chr(34)}.")
        else:
            Miscellaneous.print_message(f"Пользователю {chat_id} не удалось отправить сообщение.")

def print_error(err_msg: str, err_code: str) -> None:
    """
    * Вывод сообщения об ошибке
    *
    * @param err_msg Текст ошибки
    * @param err_code Код ошибки
    """
    Miscellaneous.print_message(err_msg)
    Miscellaneous.print_message(f"Код ошибки: {err_code}")

def run_bot(api_token: str, http_proxy: str, https_proxy: str) -> None:
    """
    * Запуск Telegram-бота
    """
    Miscellaneous.print_message("Токен успешно определён.")
    bot: telebot = None
    try:
        bot = telebot.TeleBot(api_token)
    except ValueError as err_token:
        print_error("Значение токена задано неверно.", f"{err_token}")
    if bot is not None:
        apihelper.proxy = {}  # создаём пустой словарь
        if not "".__eq__(http_proxy):
            apihelper.proxy['http'] = http_proxy
        if not "".__eq__(https_proxy):
            apihelper.proxy['https'] = https_proxy
        """
        * *************************
        * ОБРАБОТКА ЗАПРОСОВ ОТ ПОЛЬЗОВАТЕЛЯ
        * (НАЧАЛО)
        * *************************
        """
        @bot.message_handler(content_types=["text"])
        def text(message): # вся ботовская "кухня" запрятана здесь
            global cnt
            global MSG_NUMBER_LIMIT
            global debugged
            global is_irc_bot_running, irc_bot # глобальные переменные для IRC-бота
            global is_chatscript_bot_running, oChatScript # глобальные переменные для ChatScript-бота
            api_token: str = ""
            http_proxy: str = ""
            https_proxy: str = ""
            api_token, http_proxy, https_proxy = get_bot_config()
            Miscellaneous.print_message(f"Пользователь {message.from_user.id} (имя: {message.from_user.first_name}) оставил сообщение в Telegram: {chr(34)}{message.text}{chr(34)}.")
            if debugged == True: # если отладка включена, то начинаем писать в БД
                with sqlite3.connect("telegram.db") as conn:
                    cur = conn.cursor()
                    try:
                        cur.execute('''
                            create table if not exists telegram_users (
                              user_id integer primary key not null,
                              first_name text,
                              last_name text,
                              date_create text not null default current_date
                            )
                        ''')
                        cur.execute('''
                            create table if not exists user_messages (
                              user_id integer not null,
                              msg text,
                              date_create text not null default current_date,
                              foreign key (user_id) references telegram_users(user_id)
                            )
                        ''')
                        cur.execute("create index if not exists idx_user_messages_user_id_date_create on user_messages (user_id asc, date_create desc)")
                        cur.execute("insert or ignore into telegram_users (user_id, first_name, last_name) values (?, ?, ?)", (message.from_user.id, message.from_user.first_name, message.from_user.last_name))
                        cur.execute("insert into user_messages (user_id, msg) values (?, ?)", (message.from_user.id, message.text))
                        conn.commit()
                    except MemoryError as me:
                        Miscellaneous.print_message(f"Ошибка: Недостаточно памяти для загрузки всех данных. {me}")
                    except IntegrityError as e: # если запись в таблице уже есть, то просто выходим
                        pass
                    except OperationalError as e:
                        Miscellaneous.print_message(f"База данных, по всей видимости, заблокирована, или ресурс недоступен: {e}")
                    except Error as e:
                        Miscellaneous.print_message(f"Произошла ошибка: {e}")
                    finally:
                        cur.close()
            if message.text == "hello":
                send_message(bot, message.chat.id, "И тебе hello!")
            elif message.text == "/ip":
                local_ips = Miscellaneous.get_local_ip_addresses()
                if local_ips:
                    send_message(bot, message.chat.id, "Локальные IP-адреса:")
                    for ip in local_ips:
                        send_message(bot, message.chat.id, ip)
                else:
                    send_message(bot, message.chat.id, "Не удалось получить локальные IP-адреса.")
            elif message.text == "/irc":
                if is_irc_bot_running:
                    for irc_msg in irc_bot.get_irc_log(MSG_NUMBER_LIMIT):
                        send_message(bot, message.chat.id, irc_msg)
                else:
                    send_message(bot, message.chat.id, "IRC-бот не работает в данный момент.")
            elif message.text == "/username":
                send_message(bot, message.chat.id, Miscellaneous.get_username())
            elif message.text in ["/ps", "/process", "/processes"]:
                cnt = 0
                processes = Miscellaneous.get_running_processes()
                for process_name in processes:
                    if cnt >= MSG_NUMBER_LIMIT:
                        break
                    send_message(bot, message.chat.id, process_name)
                    cnt += 1
                send_message(bot, message.chat.id, f"Общее количество процессов: {len(processes)}.")
            elif message.text in ["/date", "/time"]:
                send_message(bot, message.chat.id, f"Текущая дата: {Miscellaneous.get_current_time()}.")
            elif message.text in ["/help", "/?"]:
                send_message(bot, message.chat.id, "Команды, допустимые для использования: /ip, /username, /ps, /process, /processes, /date, /time, /help, /?, /quit, /stop, /exit, /ver, /sys, /printenv, /phrase, /send, /weather, /outer_ip, /timer, /calc, /cmd, /rss, /news, /irc")
            elif message.text in ["/ver", "/sys"]:
                sys_prop = Miscellaneous.get_system_properties()
                send_message(bot, message.chat.id, f"ОС: {sys_prop[0]}, версия {sys_prop[1]}, релиз {sys_prop[2]}. ОЗУ: всего: {sys_prop[3]}; используется: {sys_prop[4]}; свободно: {sys_prop[5]}; процент использования: {sys_prop[6]}.")
            elif message.text in ["/rss", "/news"]:
                rss_titles = []
                rss_links = []
                RSS_FEED_URL: str = "https://habr.com/ru/rss/hub/webdev/all/?fl=ru"
                rss_protocol: str = (RSS_FEED_URL.split(":")[0].lower() if ":" in RSS_FEED_URL else "")
                if not "".__eq__(http_proxy) or not "".__eq__(https_proxy):
                    if rss_protocol == "http" and not "".__eq__(http_proxy):
                        rss_titles, rss_links = Miscellaneous.read_rss_feed(RSS_FEED_URL, MSG_NUMBER_LIMIT, rss_protocol, http_proxy)
                    if rss_protocol == "https" and not "".__eq__(https_proxy):
                        rss_titles, rss_links = Miscellaneous.read_rss_feed(RSS_FEED_URL, MSG_NUMBER_LIMIT, rss_protocol, https_proxy)
                else:
                    rss_titles, rss_links = Miscellaneous.read_rss_feed(RSS_FEED_URL, MSG_NUMBER_LIMIT)
                for rss_title, rss_link in zip(rss_titles, rss_links):
                    send_message(bot, message.chat.id, f"{rss_title}: {rss_link}")
            elif message.text == "/printenv":
                environment_variables = os.environ
                cnt = 0
                for key, value in environment_variables.items():
                    if cnt >= MSG_NUMBER_LIMIT:
                        break
                    send_message(bot, message.chat.id, f"{key}: {value}")
                    cnt += 1
            elif message.text == "/phrase":
                ph_choice: str = random.choice(["aphorism", "joke"])
                phrase: str = ""
                if ph_choice == "aphorism":
                    phrase = Miscellaneous.get_phrase_outta_file("phrase.txt", Constant.GLOBAL_CODEPAGE.value)
                elif ph_choice == "joke":
                    ph_proxy: str = ""
                    if not "".__eq__(http_proxy):
                        ph_proxy = http_proxy
                    elif not "".__eq__(https_proxy):
                        ph_proxy = https_proxy
                    phrase = Downgrade.jokes_script("ru", ph_proxy)
                if not "".__eq__(phrase):
                    send_message(bot, message.chat.id, phrase)
                else:
                    send_message(bot, message.chat.id, "Увы, фразы не заготовил.")
            elif (
                (message.text == "/timer")
                or (message.text.strip().startswith("/timer "))
            ):
                TIMER_ERR_MSG: str = f"Команду {chr(34)}timer{chr(34)} нужно вызывать с передачей ей количества секунд (натуральное число). Пример вызова: /timer 15"
                v_timer: str = message.text
                if v_timer == "/timer":
                    send_message(bot, message.chat.id, TIMER_ERR_MSG)
                else:
                    try:
                        timer_seconds: int = int(v_timer.split()[1])
                        if timer_seconds <= 0:
                            send_message(bot, message.chat.id, TIMER_ERR_MSG)
                        else:
                            # выделение в системе отдельного потока для таймера
                            thread: threading.Thread = threading.Thread(
                                target=lambda: ( # код обработчика таймера
                                    time.sleep(timer_seconds),
                                    send_message(bot, message.chat.id, "Время истекло!")
                                )
                            )
                            thread.start()
                            send_message(bot, message.chat.id, f"Таймер установлен на {timer_seconds} секунд.")
                    except (IndexError, ValueError):
                        send_message(bot, message.chat.id, TIMER_ERR_MSG)
            elif (
                (message.text == "/calc")
                or (message.text.strip().startswith("/calc "))
            ):
                CALC_ERR_MSG: str = f"Команду {chr(34)}calc{chr(34)} нужно вызывать с передачей ей количества секунд (любое целое число). Пример вызова: /calc -30135"
                v_calc: str = message.text
                if v_calc == "/calc":
                    send_message(bot, message.chat.id, CALC_ERR_MSG)
                else:
                    try:
                        calc_seconds: int = int(v_calc.split()[1])
                        delta_time: str = Miscellaneous.get_delta_time(calc_seconds)
                        send_message(bot, message.chat.id, f"Для заданного количества секунд ({calc_seconds}) относительно текущего времени {Miscellaneous.get_current_time()} получается следующее время: {delta_time}.")
                    except (IndexError, ValueError):
                        send_message(bot, message.chat.id, CALC_ERR_MSG)
            elif (
                (message.text == "/cmd")
                or (message.text.strip().startswith("/cmd "))
            ):
                v_cmd: str = message.text
                if v_cmd == "/cmd":
                    send_message(bot, message.chat.id, f"В строке команды {chr(34)}cmd{chr(34)} задаётся вызов программы (и возможные параметры), которую требуется выполнить под операционной системой.")
                else:
                    cmd_parts = shlex.split(v_cmd)
                    cmd_os: str = " ".join(cmd_parts[1:])
                    if not Miscellaneous.is_dangerous_command(cmd_os):
                        cmd_output_lines, cmd_return_code = Miscellaneous.run_command_from_string(cmd_os)
                        if cmd_output_lines: # Проверяем, что список не пустой
                            cnt = 0
                            for cmd_line in cmd_output_lines:
                                if cnt >= MSG_NUMBER_LIMIT:
                                    break
                                send_message(bot, message.chat.id, cmd_line)
                                cnt += 1
                            send_message(bot, message.chat.id, f"Код возврата: {cmd_return_code}")
                    else:
                        send_message(bot, message.chat.id, "Эта команда недопустима, поскольку является опасной.")
            elif (
                (message.text == "/send")
                or (message.text.strip().startswith("/send "))
            ):
                v_send: str = message.text
                if v_send == "/send":
                    send_message(bot, message.chat.id, f"Команду {chr(34)}send{chr(34)} нужно вызывать с передачей ей идентификатора получателя и текстом сообщения. Пример вызова: /send --user_id 03007 --msg Привет!_Как_у_тебя_дела?")
                    send_message(bot, message.chat.id, "Строка должна быть неразрывной, вместо пробелов следует использовать символ подчёркивания.")
                else:
                    v_send = v_send[len("/send "):].strip()
                    print(v_send)
                    send_parser = argparse.ArgumentParser(description="Отправка сообщения")
                    send_parser.add_argument("--user_id", type=int, help="Идентификатор получателя", required=True, dest="user_id")
                    send_parser.add_argument("--msg", type=str, help="Текст сообщения для получателя", required=True, dest="message")
                    try:
                        send_args = send_parser.parse_args(v_send.split())
                        send_message(bot, message.chat.id, "Отправка сообщения пользователю...")
                        send_message(bot, send_args.user_id, send_args.message)
                        send_message(bot, message.chat.id, "Сообщение отправлено пользователю.")
                    except ApiTelegramException as err_api:
                        print_error("Вероятно, нет прав для отправки сообщения указанному адресату.", f"{err_api}")
                    except SystemExit:
                        send_message(bot, message.chat.id, f"Ошибка в команде {chr(34)}send{chr(34)}.")
                        send_message(bot, message.chat.id, f"Введите {chr(34)}/send{chr(34)}, чтобы узнать, как правильно использовать команду.")
            elif message.text == "/weather":
                weather_lines = Miscellaneous.get_url("https://wttr.in/?0T", http_proxy, https_proxy)
                if weather_lines:
                    send_message(bot, message.chat.id, "Получен прогноз погоды. Данные представлены ниже.")
                    for weather_line in weather_lines:
                        send_message(bot, message.chat.id, weather_line)
                else:
                    send_message(bot, message.chat.id, "Прогноз погоды недоступен в данный момент времени.")
            elif message.text == "/outer_ip":
                outer_ip_lines = Miscellaneous.get_url("https://icanhazip.com", http_proxy, https_proxy)
                if outer_ip_lines:
                    send_message(bot, message.chat.id, "Получены данные по внешнему IP-адресу. Они представлены ниже.")
                    for outer_ip_line in outer_ip_lines:
                        send_message(bot, message.chat.id, outer_ip_line)
                else:
                    send_message(bot, message.chat.id, f"Невозможно определить {chr(34)}белый{chr(34)} IP-адрес.")
            elif message.text.lower() in ["/quit", "/stop", "/exit"]: # команда завершения работы бота
                send_message(bot, message.chat.id, "Goodbye, cruel world! Никогда больше к вам не вернусь.")
                bot.stop_poll
                quit_app()
            else: # если ничего выше не совпало, то передаём управление серверу ChatScript
                if is_chatscript_bot_running == True and oChatScript is not None:
                    chatscript_bot_response: str = oChatScript.send_user_message(message.text)
                    if not "".__eq__(chatscript_bot_response):
                        send_message(bot, message.chat.id, chatscript_bot_response)
        """
        * *************************
        * ОБРАБОТКА ЗАПРОСОВ ОТ ПОЛЬЗОВАТЕЛЯ
        * (КОНЕЦ)
        * *************************
        """
        Miscellaneous.print_message("Telegram-бот запущен и ожидает команд пользователя в мессенджере.")
        Miscellaneous.print_message("Для остановки программы нажмите Ctrl+C в текущем сеансе или введите /quit в Telegram.")
        try:
            bot.polling(none_stop=False, interval=0)
        except KeyboardInterrupt: # перехват Ctrl+C
            pass
        except ProxyError as err_proxy:
            print_error("Произошла ошибка proxy-сервера.", f"{err_proxy}")
        except ApiTelegramException as err_api:
            print_error("Произошла ошибка доступа к Telegram API.", f"{err_api}")
        except ReadTimeout as err_read:
            print_error("Слишком большое время отклика от сервера Telegram.", f"{err_read}")
        except ValueError as err_token:
            print_error("Значение токена задано неверно.", f"{err_token}")
    return

def run_irc_bot() -> IRCBot:
    """
    * Запуск бота IRC (в отдельном потоке)
    *
    * @return Список последних записей в виде массива строк
    """
    IRC_SECTION: str = "irc"
    IRC_CHANNEL: str = "channel"
    IRC_NICKNAME: str = "nickname"
    IRC_SERVER: str = "server"
    IRC_PORT: str = "port"
    IRC_CODEPAGE: str = "codepage"
    bot: IRCBot = None
    config = configparser.ConfigParser()
    try:
        with open(Constant.SETTINGS_FILE.value, 'r', encoding=Constant.GLOBAL_CODEPAGE.value) as f:
            config.read_file(f)
            if IRC_SECTION in config:
                if IRC_CHANNEL in config[IRC_SECTION]:
                    l_channel: str = config[IRC_SECTION][IRC_CHANNEL].strip()
                    if "".__eq__(l_channel):
                        raise ValueError("Канал IRC не задан")
                if IRC_NICKNAME in config[IRC_SECTION]:
                    l_nickname: str = config[IRC_SECTION][IRC_NICKNAME].strip()
                    if "".__eq__(l_nickname):
                        raise ValueError("Имя пользователя в IRC не задано")
                if IRC_SERVER in config[IRC_SECTION]:
                    l_server: str = config[IRC_SECTION][IRC_SERVER].strip()
                    if "".__eq__(l_server):
                        raise ValueError("Не указан хост сервера IRC")
                if IRC_PORT in config[IRC_SECTION]:
                    l_port: int = config.getint(IRC_SECTION, IRC_PORT)
                    if not (1 <= l_port <= 65534):
                        raise ValueError("Значение порта вне допустимого диапазона (1 - 65534)")
                l_codepage: str = ""
                if IRC_CODEPAGE in config[IRC_SECTION]:
                    l_codepage = config[IRC_SECTION][IRC_CODEPAGE].strip()
                l_codepage = "utf-8" if "".__eq__(l_codepage) else l_codepage
            """
            * Переопределяем буфер декодирования входящего потока для всех подключений библиотеки irc.
            * LenientDecodingLineBuffer сначала пробует UTF-8, затем откатывается к latin-1 - это
            * предотвращает ошибку декодирования при подключении к серверам с нестандартной кодировкой
            * (например, CP1251) и позволяет корректно обрабатывать входящие строки.
            """
            from jaraco.stream import buffer
            import irc.client
            irc.client.ServerConnection.buffer_class = buffer.LenientDecodingLineBuffer
            bot = IRCBot(l_channel, l_nickname, l_server, l_port, l_codepage)
            Miscellaneous.print_message("Запуск IRC-бота...")
            thread: threading.Thread = threading.Thread(
                target=lambda: (
                    bot.start()
                ),
                daemon = True # если основной поток завершится, демон-поток будет автоматически остановлен
            )
            thread.start()
            time.sleep(10)
    except FileNotFoundError:
        Miscellaneous.print_message(f"Ошибка: Файл настроек не найден: {Constant.SETTINGS_FILE.value}")
    except ValueError:
        Miscellaneous.print_message("Значение параметра не соответствует типу данных в конфигурационном файле.")
    except Exception as e:
        Miscellaneous.print_message(f"Ошибка при чтении файла настроек: {e}")
    return bot

def get_chatscript_config():
    """
    * Получение конфигурации для работы клиента ChatScript
    *
    * @return Хост сервера, порт сервера
    """
    CHATSCRIPT_SECTION: str = "chatscript"
    CHATSCRIPT_SERVER: str = "server"
    CHATSCRIPT_PORT: str = "port"
    config = configparser.ConfigParser()
    try:
        with open(Constant.SETTINGS_FILE.value, 'r', encoding=Constant.GLOBAL_CODEPAGE.value) as f:
            config.read_file(f)
            if CHATSCRIPT_SECTION in config:
                l_server: str = ""
                l_port: int = 0
                if CHATSCRIPT_SERVER in config[CHATSCRIPT_SECTION]:
                    l_server = config[CHATSCRIPT_SECTION][CHATSCRIPT_SERVER].strip()
                    if "".__eq__(l_server):
                        raise ValueError("Не указан хост сервера IRC")
                if CHATSCRIPT_PORT in config[CHATSCRIPT_SECTION]:
                    l_port = config.getint(CHATSCRIPT_SECTION, CHATSCRIPT_PORT)
                    if not (1 <= l_port <= 65534):
                        raise ValueError("Значение порта вне допустимого диапазона (1 - 65534)")
                return l_server, l_port
    except FileNotFoundError: # Ошибка: Файл настроек не найден
        print(f"Ошибка: Файл настроек не найден: {Constant.SETTINGS_FILE.value}")
        return None, None
    except ValueError: # Значение параметра не соответствует типу данных в конфигурационном файле
        print("Значение параметра не соответствует типу данных в конфигурационном файле.")
        return None, None
    except Exception as e: # Ошибка при чтении файла настроек
        print(f"Ошибка при чтении файла настроек: {e}")
        return None, None

def quit_app() -> None:
    """
    * Завершение работы программы
    """
    global is_irc_bot_running, irc_bot # глобальные переменные для IRC-бота
    Miscellaneous.print_message("Выполняется завершение работы программы...")
    if is_irc_bot_running: # корректное завершение работы IRC-бота
        try:
            irc_bot.connection.quit()
        except ServerNotConnectedError:
            pass
        time.sleep(3)
        is_irc_bot_running = False
        Miscellaneous.print_message("IRC-бот остановлен.")
    Miscellaneous.print_message("Завершение работы Telegram-бота.")
    os._exit(0)

def main() -> None:
    global is_irc_bot_running, irc_bot # глобальные переменные для IRC-бота
    global is_chatscript_bot_running, oChatScript # глобальные переменные для ChatScript-бота
    chatscript_host: str = None
    chatscript_port: int = None
    api_token: str = ""
    http_proxy: str = ""
    https_proxy: str = ""
    Miscellaneous.print_message("Запуск Telegram-бота...")
    if Miscellaneous.is_file_readable(Constant.SETTINGS_FILE.value):
        Miscellaneous.print_message(f"Файл настроек найден: {Constant.SETTINGS_FILE.value}")
        api_token, http_proxy, https_proxy = get_bot_config()
    else:
        Miscellaneous.print_message(f"Ошибка: Файл настроек не найден: {Constant.SETTINGS_FILE.value}")
    if "".__eq__(api_token):
        Miscellaneous.print_message("Токен для Telegram-бота не найден.")
    else:
        chatscript_host, chatscript_port = get_chatscript_config()
        if chatscript_host is not None and chatscript_port is not None:
            oChatScript = ChatScript(chatscript_host, chatscript_port)
            if oChatScript.is_server_running():
                chatscript_init: str = oChatScript.server_reset() # инициализация бота ChatScript
                if not "".__eq__(chatscript_init):
                    is_chatscript_bot_running = True
                    Miscellaneous.print_message(f"Проинициализирован бот ChatScript. Получен ответ от сервера: {chr(34)}{chatscript_init}{chr(34)}.")
        irc_bot = run_irc_bot()
        is_irc_bot_running = True if irc_bot is not None and irc_bot.is_connected else False
        run_bot(api_token, http_proxy, https_proxy)
    quit_app()
    return

# Точка запуска программы
if __name__ == "__main__":
    main()
