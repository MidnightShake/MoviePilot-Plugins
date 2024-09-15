from typing import List, Tuple, Dict, Any

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.db.transferhistory_oper import TransferHistoryOper
from app.log import logger
from app.plugins import _PluginBase

import datetime
import json
import os
import sqlite3
import hmac
import hashlib

# 默认py3 需要安装: pip install pycryptodome
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

class CookieCompanion(_PluginBase):
    # 插件名称
    plugin_name = "cookie伴侣"
    # 插件描述
    plugin_desc = "搭配浏览器插件导入MP本地储存的有效站点Cookie。"
    # 插件图标
    plugin_icon = "Chrome_A.png"
    # 插件版本
    plugin_version = "0.1"
    # 插件作者
    plugin_author = "MidnightShake"
    # 作者主页
    author_url = "https://github.com/MidnightShake"
    # 插件配置项ID前缀
    plugin_config_prefix = "cookiecompanion_"
    # 加载顺序
    plugin_order = 167
    # 可使用的用户级别
    user_level = 1

    # 私有属性
    _scheduler = None
    _enabled = False
    _onlyonce = False
    _uuid = ""
    _key = ""
    _cron = None
    _server_address = ""

    def init_plugin(self, config: dict = None):
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._uuid = config.get("uuid")
            self._key = config.get("key")
            self._cron = config.get("cron") or ""
            self._server_address = config.get("server_address") or ""

        # 停止现有任务
        self.stop_service()

        # 启动定时任务 & 立即运行一次
        if self._enabled or self._onlyonce:
            self.transferhis = TransferHistoryOper()

            if not self._uuid or not self._key:
                self._onlyonce = False
                # 保存配置
                self.update_config({
                    "onlyonce": False,
                    "enabled": False,
                    "uuid": self._uuid,
                    "key": self._key,
                    "cron": self._cron,
                    "server_address": self._server_address
                })
                logger.info(f"cookie伴侣服务未成功运行：插件内 用户UUID 或 端对端加密密码 不能为空")
                return
            
            if self._onlyonce:
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.info(f"cookie伴侣服务，立即运行一次")
                self._scheduler.add_job(func=self.__cookiecompanion, trigger='date',
                                        run_date=datetime.datetime.now(tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3),
                                        name="cookie伴侣服务")
                # 关闭一次性开关
                self._onlyonce = False
                # 保存配置
                self.update_config({
                    "onlyonce": False,
                    "enabled": self._enabled,
                    "uuid": self._uuid,
                    "key": self._key,
                    "cron": self._cron,
                    "server_address": self._server_address
                })

            # 启动定时服务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self._enabled and self._cron:
            return [{
                "id": "cookiecompanion",
                "name": "cookie伴侣",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.__cookiecompanion,
                "kwargs": {}
            }]
        elif self._enabled:
            return [{
                "id": "cookiecompanion",
                "name": "cookie伴侣",
                "trigger": CronTrigger.from_crontab("0 0 */1 * *"),
                "func": self.__cookiecompanion,
                "kwargs": {}
            }]
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'uuid',
                                            'label': '用户UUID',
                                            'placeholder': '16位(英文字母大小写+数字组合)'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'key',
                                            'label': '端对端加密密码',
                                            'placeholder': '16位(英文字母大小写+数字组合)'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '用户UUID 不可与CookieCloud服务器 的用户KEY/UUID相同。'
                                                    '此插件调用CookieCloud服务器相同API存取数据，但不兼容相互加解密数据。'
                                                    '设置与CookieCloud服务器相同用户KEY/UUID会造成CookieCloud服务器数据被覆盖丢失。'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 6
                        },
                        'content': [
                            {
                                'component': 'VTextField',
                                'props': {
                                    'model': 'cron',
                                    'label': '执行周期(更新插件本地加密cookie数据)',
                                    'placeholder': '5位cron表达式，留空自动每1小时运行一次'
                                }
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'server_address',
                                            'label': '服务地址',
                                            'rows': 2,
                                            'placeholder': '使用MP内建CookieCloud服务地址则留空'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '使用MP内建CookieCloud服务地址,需在--设定--站点--站点同步--勾选启用本地CookieCloud服务。'
                                                    '如果使用第三方/另自建CookieCloud服务，则填入完整服务地址格式如：http://localhost:3000/cookiecloud'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "cron": "0 0 */1 * *",
            "server_address": "http://localhost:3000/cookiecloud"
        }

    def get_page(self) -> List[dict]:
        pass

    def __cookiecompanion(self):
        if self._key or self._uuid:
            # 定义 获取到的json格式 文件名及路径
            load_json_data_path = "/config/" + self._uuid + "_cookie_data.json"
            # 定义 加密后的json格式 文件名及路径
            encrypted_data_path = "/config/" + "cookies/" + self._uuid + ".json"
            # 获取获取MP有效站点cookie数据
            rows_dict = self.__connect_db()
            # 检查并更新插件本地cookie数据
            sum = self.__rows_dict_to_path(rows_dict, load_json_data_path)
            if sum == 1:
                # 加密数据
                encrypted_data = self.__encrypt(json.dumps(rows_dict), self._key, self._uuid)
                # 加密数据格式化及储存处理
                self.__save_encrypted_data(encrypted_data, encrypted_data_path)

    def __connect_db(self):
        """
        获取MP有效站点cookie数据
        """
        # 定义目标数据库 文件名
        source_db_path = '/config/user.db'
        # 定义目标数据库 表名
        table_name = 'site'
        # 定义目标数据库 列名
        columns_to_select = ['id', 'domain', 'url', 'cookie', 'lst_mod_date']
        # 获取数据
        source_conn = sqlite3.connect(source_db_path)
        source_cursor = source_conn.cursor()
        source_cursor.execute("SELECT name FROM sqlite_master WHERE type='Table'")
        Tables = source_cursor.fetchall()
        source_cursor.execute(f"SELECT {', '.join(columns_to_select)} FROM {table_name}")
        rows_dict = {}
        for row in Tables:
            domain = row[1]
            if domain not in rows_dict:
                rows_dict[domain] = []
            row_dict = {col: val for col, val in zip(columns_to_select, row)}
            rows_dict[domain].append(row_dict)
        source_conn.close()
        return rows_dict

    def __rows_dict_to_path(self, rows_dict, load_json_data_path):
        """
        检查并更新插件本地cookie数据文件
        """
        sum = 0
        if rows_dict:
            if os.path.exists(load_json_data_path):
                # 加载数据文件内容
                if os.path.getsize(load_json_data_path) > 0:
                    with open(load_json_data_path, 'r') as json_file:
                        json_data = json.load(json_file)
                else:
                    json_data = {}
                # 比较并更新数据文件内容
                if json_data != rows_dict:
                    for domain, rows in rows_dict.items():
                        if domain in json_data:
                            for row in rows:
                                if row != json_data[domain]:
                                    json_data[domain] = row
                        else:
                            json_data[domain] = rows
                    with open(load_json_data_path, 'w') as json_file:
                        json.dump(json_data, json_file)
                    sum = 1
            else:
                # 如果数据文件不存在，新建并写入文件
                with open(load_json_data_path, 'w') as file:
                    file.write(json.dumps(rows_dict))
                sum = 1
        return sum

    def __encrypt(self, decrypt_data, key, iv):
        """
        encrypt方法
        """
        cipher = AES.new(self.__generateHash(key, iv)[:16].encode(), AES.MODE_CBC, self.__generateHash(key, iv)[16:32].encode())
        encrypt_data = cipher.encrypt(pad(decrypt_data.encode(), AES.block_size))
        return encrypt_data.hex()

    def __save_encrypted_data(self, destination_data, destination_data_path):
        """
        encrypt数据格式化及储存
        """
        format_data = json.dumps({"encrypted": destination_data})
        with open(destination_data_path, 'w') as file:
            file.write(format_data)
        if self._server_address != 'http://localhost:3000/cookiecloud':
            self.__encrypted_data_post_other_server(self._server_address, destination_data_path)

    def __encrypted_data_post_other_server(self, server_address, destination_data_path):
        """
        发送已加密数据至自定义CookieCloud服务地址储存
        """
        pass

    def __generateHash(self, key, uuid):
        """
        生成Hash字符串函数
        """
        data = key.encode() + uuid.encode()
        hash_obj = hmac.new(key.encode(), data, hashlib.md5)
        hash_str = hash_obj.hexdigest()
        return hash_str
    
    def stop_service(self):
        """
        退出插件
        """
        pass
