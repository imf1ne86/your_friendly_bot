"""
* Класс для обеспечения функционирования IRC-бота
* *************************
* В данном классе содержится весь необходимый функционал для
* обеспечения работоспособности бота в сети IRC (RFC 1459).
* Для работы программы требуется Python 3. Предварительно
* требуется установить необходимые библиотеки:
* $ pip3 install --trusted-host pypi.org --trusted-host files.pythonhosted.org --upgrade pip
* $ pip3 install --trusted-host pypi.org --trusted-host files.pythonhosted.org irc
* https://github.com/jaraco/irc
* Программа является кроссплатформенной. Она должна работать
* под Microsoft Windows, Linux, macOS и т.д.
*
* @author Ефремов А. В., 21.08.2025
"""

from irc.bot import SingleServerIRCBot
import irc.strings
import sqlite3
from sqlite3 import IntegrityError, OperationalError, Error

class IRCBot(SingleServerIRCBot):
    DB_FILENAME: str = "irc.db" # база данных для хранения чатлогов IRC
    is_connected: bool = False # признак подключения к серверу IRC (по умолчанию не подключён)

    def __init__(self, channel: str, nickname: str, server: str, port: int = 6667, encoding: str = "utf-8"):
        SingleServerIRCBot.__init__(self, [(server, port)], nickname, nickname)
        self.channel = channel
        self.encoding = encoding

    def irc_log(self, msg: str) -> None:
        """
        * Запись сообщения в консоль и в базу данных
        *
        * @param msg Текст сообщения
        """
        if not "".__eq__(msg):
            with sqlite3.connect(self.DB_FILENAME) as conn:
                cur = conn.cursor()
                try:
                    cur.execute('''
                        create table if not exists irc_log (
                          message text,
                          date_create text not null default current_timestamp
                        )
                    ''')
                    cur.execute("insert into irc_log (message) values (?)", (msg,))
                    conn.commit()
                except MemoryError as me:
                    print(f"Ошибка: Недостаточно памяти для загрузки всех данных. {me}")
                except IntegrityError as e: # если запись в таблице уже есть, то просто выходим
                    pass
                except OperationalError as e:
                    print(f"База данных, по всей видимости, заблокирована, или ресурс недоступен: {e}")
                except Error as e:
                    print(f"Произошла ошибка: {e}")
                finally:
                    cur.close()
            print(msg)

    def get_irc_log(self, p_limit: int = 15):
        """
        * Получение последних записей из лога (база данных)
        *
        * @return Список последних записей в виде массива строк
        """
        l_limit: int = p_limit
        if l_limit < 1:
            l_limit = 1
        if l_limit > 1000:
            l_limit = 1000
        QUERY: str = f"select r2.msg from (select r.msg, r.rn from (select l.message as msg, row_number() over () as rn from irc_log l) r order by r.rn desc limit {l_limit}) r2 order by r2.rn asc"
        data_array = [] # Инициализируем пустой массив
        result = []
        with sqlite3.connect(self.DB_FILENAME) as conn:
            cur = conn.cursor()
            try:
                cur.execute(QUERY)
                rows = cur.fetchall() # получаем результаты
                for row in rows:
                    data_array.append(row)
            except MemoryError as me:
                print(f"Ошибка: Недостаточно памяти для загрузки всех данных. {me}")
            except IntegrityError as e:
                print(f"Возникла ошибка целостности: {e}")
            except OperationalError as e:
                print(f"База данных, по всей видимости, заблокирована, или ресурс недоступен: {e}")
            except Error as e:
                print(f"Произошла ошибка: {e}")
            finally:
                cur.close()
        if len(data_array) > 0:
            for item in data_array:
                for element in item:
                    result.append(element)
        return result

    def do_command(self, event, cmd: str):
        """
        * Обработчик команд для текущего бота
        *
        * @param event Экземпляр объекта "Событие"
        * @param cmd Команда
        """
        nick = event.source.nick
        connection = self.connection
        if cmd == "disconnect" or cmd == "die":
            self.die()
        elif cmd == "stats":
            for chname, chobj in self.channels.items():
                connection.notice(nick, "--- Channel statistics ---")
                connection.notice(nick, "Channel: " + chname)
                users = sorted(chobj.users())
                connection.notice(nick, "Users: " + ", ".join(users))
                opers = sorted(chobj.opers())
                connection.notice(nick, "Opers: " + ", ".join(opers))
                voiced = sorted(chobj.voiced())
                connection.notice(nick, "Voiced: " + ", ".join(voiced))
        else:
            connection.notice(nick, "Not understood: " + cmd)

    def on_nicknameinuse(self, connection, event):
        connection.nick(connection.get_nickname() + "_")

    def on_welcome(self, connection, event):
        """
        * Обработчик события "Подключение к серверу IRC"
        *
        * @param connection Экземпляр объекта "Соединение"
        * @param event Экземпляр объекта "Событие"
        """
        self.is_connected = True
        try: # попробуем задать encoding у объекта connection, если он поддерживает
            if hasattr(connection, "encoding"):
                connection.encoding = self.encoding
        except Exception:
            pass
        connection.join(self.channel)

    def send_message(self, connection, msg: str) -> None:
        """
        * Отправка сообщения пользователю в канал
        *
        * @param connection Экземпляр объекта "Соединение"
        * @param msg Текст сообщения
        """
        if not "".__eq__(msg):
            try: # некоторые реализации ожидают str, некоторые - bytes
                connection.privmsg(self.channel, msg)
            except TypeError:
                connection.privmsg(self.channel, msg.encode(self.encoding, errors="replace"))
            self.irc_log(f"<{connection.get_nickname()}> {msg}")

    def on_pubmsg(self, connection, event):
        """
        * Обработчик сообщения в канале
        *
        * @param connection Экземпляр объекта "Соединение"
        * @param event Экземпляр объекта "Событие"
        """
        sender = event.source.nick
        raw = event.arguments[0]
        if isinstance(raw, (bytes, bytearray)):
            try:
                message = raw.decode(self.encoding, errors="replace")
            except Exception:
                message = raw.decode("utf-8", errors="replace")
        else:
            message = raw
        self.irc_log(f"<{sender}> {message}")
        # ответить на определённое сообщение
        if message.lower() == "hello":
            self.send_message(connection, f"Hello, {sender}!")
        elif message.lower() == "bye":
            self.send_message(connection, f"Bye, {sender}!")
        # поиск в сообщении команды, адресованной текущему боту
        a = message.split(":", 1)
        if len(a) > 1 and irc.strings.lower(a[0]) == irc.strings.lower(self.connection.get_nickname()):
            self.do_command(event, a[1].strip())

    def on_disconnect(self, connection, event):
        """
        * Обработчик события "Отключение от сервера IRC"
        *
        * @param connection Экземпляр объекта "Соединение"
        * @param event Экземпляр объекта "Событие"
        """
        self.is_connected = False
        self.irc_log("Disconnected.")
