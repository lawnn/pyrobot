import json
import sys
import os
import requests
import logging
from logging.handlers import RotatingFileHandler
from .logfile import OrderHistory
from .time_util import now_jst_str


class Log(object):
    def __init__(self, path):
        try:
            self.apis = self.config = json.load(open(path, 'r', encoding="utf-8"))
        except FileNotFoundError as e:
            print("[ERROR] Config file is not found.", file=sys.stderr)
            raise e
        except ValueError as e:
            print("[ERROR] Json file is invalid.", file=sys.stderr)
            raise e
        self.logger = None

        try:
            self.exchange_name = self.config["exchange_name"]
        except KeyError:
            self.exchange_name = 'Exchange'
            pass
        try:
            self.bot_name = self.config["bot_name"]
        except KeyError:
            self.bot_name = 'Bot'
        try:
            self.log_level = self.config["log_level"]
        except KeyError:
            self.log_level = 'DEBUG'
        try:
            self.log_dir = self.config["log_dir"]
        except KeyError:
            self.log_dir = 'log'

    def _initialize_logger(self):
        """
        ロガーを初期化します.
        """
        if not self.logger:
            self.logger = logging.getLogger(f"{self.exchange_name}_{self.bot_name}")
            self.logger.setLevel(self.log_level)
            if not self.logger.hasHandlers():
                stream_formatter = logging.Formatter(fmt="[%(levelname)s] %(asctime)s : %(message)s",
                                                     datefmt="%Y-%m-%d %H:%M:%S")
                stream_handler = logging.StreamHandler()
                stream_handler.setFormatter(stream_formatter)
                stream_handler.setLevel(self.log_level)
                self.logger.addHandler(stream_handler)
                if self.log_dir:
                    # コンフィグファイルでログディレクトリが指定されていた場合、ファイルにも出力します.
                    if not os.path.exists(self.log_dir):
                        os.mkdir(self.log_dir)
                    file_formatter = logging.Formatter(fmt="[%(levelname)s] %(asctime)s %(module)s: %(message)s",
                                                       datefmt="%Y-%m-%d %H:%M:%S")
                    file_handler = RotatingFileHandler(
                        filename=os.path.join(self.log_dir, f"{self.exchange_name}_{self.bot_name}.log"),
                        maxBytes=1024 * 1024 * 2, backupCount=3)
                    file_handler.setFormatter(file_formatter)
                    file_handler.setLevel(self.log_level)
                    self.logger.addHandler(file_handler)

    def log_error(self, message):
        """
        ERRORレベルのログを出力します.
        :param message: ログメッセージ.
        """
        self.logger.error(message)

    def log_exception(self, message):
        """
        Exceptionレベルのログを出力します.
        :param message: ログメッセージ.
        """
        self.logger.exception(message)

    def log_warning(self, message):
        """
        WARNINGレベルのログを出力します.
        :param message: ログメッセージ.
        """
        self.logger.warning(message)

    def log_info(self, message):
        """
        INFOレベルのログを出力します.
        :param message: ログメッセージ.
        """
        self.logger.info(message)

    def log_debug(self, message):
        """
        DEBUGレベルのログを出力します.
        :param message: ログメッセージ.
        """
        self.logger.debug(message)


class Notify(Log):
    def __init__(self, path):
        super().__init__(path)
        self._initialize_logger()

        # ラインに稼働状況を通知
        try:
            self.line_notify_token = self.config["line_notify_token"]
        except KeyError:
            pass
        # Discordに稼働状況を通知するWebHook
        try:
            self.discordWebhook = self.config["discordWebhook"]
        except KeyError:
            # 設定されていなければNoneにしておく
            self.discordWebhook = None

    def lineNotify(self, message, fileName=None):
        payload = {'message': message}
        headers = {'Authorization': 'Bearer ' + self.line_notify_token}
        if fileName is None:
            try:
                requests.post('https://notify-api.line.me/api/notify', data=payload, headers=headers)
                self.log_info(message)
            except Exception as e:
                self.log_error(e)
                raise e
        else:
            try:
                files = {"imageFile": open(fileName, "rb")}
                requests.post('https://notify-api.line.me/api/notify', data=payload, headers=headers, files=files)
            except Exception as e:
                self.log_error(e)
                raise e

    # config.json内の[discordWebhook]で指定されたDiscordのWebHookへの通知
    def discordNotify(self, message, fileName=None):
        payload = {"content": " " + message + " "}
        if fileName is None:
            try:
                requests.post(self.discordWebhook, data=payload)
                self.log_info(message)
            except Exception as e:
                self.log_error(e)
                raise e
        else:
            try:
                files = {"imageFile": open(fileName, "rb")}
                requests.post(self.discordWebhook, data=payload, files=files)
            except Exception as e:
                self.log_error(e)
                raise e

    def statusNotify(self, message, fileName=None):
        # config.json内に[discordWebhook]が設定されていなければLINEへの通知
        if self.discordWebhook is None:
            self.lineNotify(message, fileName)
        else:
            # config.json内に[discordWebhook]が設定されていればDiscordへの通知
            self.discordNotify(message, fileName)


class BotBase(Notify):
    def __init__(self, path):
        super().__init__(path)
        self.stop_flag = False
        # 発注履歴ファイルを保存するファイルのパラメータ
        try:
            self.order_history_dir = self.config["log_dir"]
        except KeyError:
            self.order_history_dir = 'log'
        self.columns = {}
        # csvファイルを書き込む場所
        self.order_history_file_name_base = f"{self.exchange_name}_{self.bot_name}_order_history"
        self.order_history_files = {}
        self.order_history_file_class = OrderHistory


    async def start(self):
        """
        ボットを起動します.
        """
        await self._run_logic()
        self.log_info("Bot started.")


    def stop(self):
        """
        ボットを停止します.
        """
        self.stop_flag = True
        self.log_info("Logic threads has been stopped.")


    async def _run_logic(self):
        """
        ロジック部分です. 子クラスで実装します.
        """
        raise NotImplementedError()


    def write_order_history(self, order_history):
        """
        発注履歴を出力します.
        :param order_history: ログデータ.
        """
        self.get_or_create_order_history_file().write_row_by_dict(order_history)


    def get_or_create_order_history_file(self):
        """
        現在時刻を元に発注履歴ファイルを取得します.
        ファイルが存在しない場合、新規で作成します.
        :return: 発注履歴ファイル.
        """
        today_str = now_jst_str("%y%m%d")
        order_history_file_name = self.order_history_file_name_base + f"_{today_str}.csv"
        full_path = self.order_history_dir + "/" + order_history_file_name
        if today_str not in self.order_history_files:
            self.order_history_files[today_str] = self.order_history_file_class(full_path, self.columns)
            self.order_history_files[today_str].open()
        return self.order_history_files[today_str]


    def close_order_history_files(self):
        """
        発注履歴ファイルをクローズします.
        """
        for order_history_file in self.order_history_files.values():
            order_history_file.close()