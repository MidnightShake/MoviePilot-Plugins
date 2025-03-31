from typing import Any, List, Dict, Tuple
from urllib.parse import quote_plus

from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils


class GotifyMsgPush(_PluginBase):
    # 插件名称
    plugin_name = "Gotify消息推送"
    # 插件描述
    plugin_desc = "支持使用Gotify推送消息通知。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/gotify/logo/master/gotify-logo.png"
    # 插件版本
    plugin_version = "2.2"
    # 插件作者
    plugin_author = "MidnightShake"
    # 作者主页
    author_url = "https://github.com/MidnightShake"
    # 插件配置项ID前缀
    plugin_config_prefix = "gotifymsgpush_"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _onlyonce = False
    _msgtypes = []
    _server = None
    _apikey = None
    _priority = None
    _params = None
    _diy_title = None
    _diy_message = None

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._msgtypes = config.get("msgtypes") or []
            self._server = config.get("server")
            self._apikey = config.get("apikey")
            self._priority = config.get("priority")
            self._diy_title = config.get("diy_title")
            self._diy_message = config.get("diy_message")

            if self._onlyonce:
                logger.info(f"Gotify消息推送服务启动,立即向服务器发送一次 自定义消息")
                if not self._diy_title and self._diy_message:
                    self._diy_title = '来MP的Gotify消息推送 <测试标题>'
                elif self._diy_title and not self._diy_message:
                    self._diy_message = '来MP的Gotify消息推送 <测试内容>'
                elif not self._diy_title and not self._diy_message:
                    self._diy_title = '来MP的Gotify消息推送 <测试标题>'
                    self._diy_message = '来MP的Gotify消息推送 <测试内容>'
                self.send(Event)
                # 关闭一次性开关
                self._onlyonce = False
                # 清空自定义内容
                self._diy_title = ''
                self._diy_message = ''
                # 保存配置
                self.__update_config()
            elif not self._diy_title or not self._diy_message:
                # 清空自定义内容
                self._diy_title = ''
                self._diy_message = ''
                # 保存配置
                self.__update_config()


    def get_state(self) -> bool:
        return self._enabled and (True if self._server and self._apikey else False)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面,需要返回两块数据:1、页面配置；2、数据结构
        """
        # 编历 NotificationType 枚举,生成消息类型选项
        MsgTypeOptions = []
        for item in NotificationType:
            MsgTypeOptions.append({
                "title": item.value,
                "value": item.name
            })
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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'server',
                                            'label': '服务器地址',
                                            'placeholder': '(示例) https://api.day.app:8385',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'apikey',
                                            'label': '密钥',
                                            'placeholder': '',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'priority',
                                            'label': '消息级别',
                                            'placeholder': '',
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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'model': 'msgtypes',
                                            'label': '消息类型',
                                            'items': MsgTypeOptions
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
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即发送一次 自定义消息',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'diy_title',
                                            'label': '输入自定义消息的 标题',
                                            'placeholder': '(不能留空)',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'diy_message',
                                            'label': '输入自定义消息的 内容',
                                            'placeholder': '(不能留空)',
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
            "onlyonce": False,
            'msgtypes': [],
            'server': '',
            'apikey': '',
            'priority': '0',
            'diy_title': '',
            'diy_message': '',
        }

    def get_page(self) -> List[dict]:
        pass

    def __update_config(self):
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "msgtypes": self._msgtypes,
            "server": self._server,
            "apikey": self._apikey,
            "priority": self._priority,
            "diy_title": '',
            "diy_message": ''
        })

    @eventmanager.register(EventType.NoticeMessage)
    def send(self, event: Event):
        """
        消息发送事件
        """
        if self._diy_title and self._diy_message:
            logger.info(f"Gotify消息推送服务检测到一次 测试消息待发送...")
            # 标题
            title = self._diy_title
            # 文本
            text = self._diy_message
        else:
            # logger.info(f"Gotify消息通知服务检测到消息")
            if not self.get_state() or not event.event_data:
                # logger.info(f"Gotify消息通知服务未启动")
                return

            msg_body = event.event_data
            # 渠道
            channel = msg_body.get("channel")
            if channel:
                # logger.info(f"消息未发送")
                return
            # 类型
            msg_type: NotificationType = msg_body.get("mtype")
            logger.info(msg_type)
            # 标题
            title = msg_body.get("title")
            # 文本
            text = msg_body.get("text")
            if (text is not None or text != "") and (title is None or title == ""):
                title = text
            elif (text is None or text == "") and (title is not None or title != ""):
                text = title

            if (msg_type and self._msgtypes
                    and msg_type.name not in self._msgtypes):
                logger.info(f"消息类型 {msg_type.value} 在Gotify推送插件中 未开启")
                return

        try:
            if not title or not text:
                logger.warn("标题和内容不能为空")
                return
            if not self._server or not self._apikey or not self._priority:
                logger.info("Gotify消息推送 参数未配置")
                return False, "参数未配置"
            sc_url = "%s/%s" % (self._server, 'message?token=' + self._apikey)
            data = {
                "title": title,
                "message": text,
                "priority": self._priority
            }
            res = RequestUtils().post_res(url = sc_url, data = data)
            if res or res is not None:
                if res.status_code == 200:
                    logger.info("Gotify消息发送成功")
                elif res.status_code == 400:
                    logger.warn(f"Gotify消息发送失败,错误码:{res.status_code},错误原因:{res.reason}, 返回信息:{res}: 发送的消息格式错误或不兼容!")
                elif res.status_code == 401:
                    logger.warn(f"Gotify消息发送失败,错误码:{res.status_code},错误原因:{res.reason}, 返回信息:{res}: 未经授权的错误-令牌无效!")
                elif res.status_code == 403:
                    logger.warn(f"Gotify消息发送失败,错误码:{res.status_code},错误原因:{res.reason}, 返回信息:{res}: 本插件端已被gotify服务器端禁止!")
                elif res.status_code == 404:
                    logger.warn(f"Gotify消息发送失败,错误码:{res.status_code},错误原因:{res.reason}, 返回信息:{res}: API URL未找到!")
                else:
                    logger.warn(f"Gotify消息发送失败,错误码:{res.status_code},错误原因:{res.reason}, 返回信息:{res}: 发送的 消息标题:{title},消息内容:{text}")
            else:
                logger.warn(f"Gotify消息发送失败:未获取到返回信息!")
        except Exception as msg_e:
            logger.error(f"Gotify消息发送失败 错误:{(msg_e)},发送的 消息标题:{title},消息内容:{text}")

    def stop_service(self):
        """
        退出插件
        """
        pass
