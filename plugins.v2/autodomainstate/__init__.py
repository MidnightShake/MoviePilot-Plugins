from typing import Any, List, Dict, Tuple, Optional
from pathlib import Path
from datetime import datetime, timedelta
import concurrent.futures
from collections import defaultdict
import pytz

from app.core.event import EventManager, eventmanager, Event
from app.helper.sites import SitesHelper
from app.log import logger
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType

from app.db import DbOper
from app.core.config import settings
from app.db.site_oper import SiteOper

from app.chain.site import SiteChain

class AutoDomainState(_PluginBase):
    # 插件名称
    plugin_name = "监测站点访问状态提醒"
    # 插件描述
    plugin_desc = "监测站点访问状态，推送访问失败的站点消息。"
    # 插件图标
    plugin_icon = "Chatgpt_A.png"
    # 插件版本
    plugin_version = "1.6"
    # 插件作者
    plugin_author = "MidnightShake"
    # 作者主页
    author_url = "https://github.com/MidnightShake"
    # 插件配置项ID前缀
    plugin_config_prefix = "autodomainstate_"
    # 加载顺序
    plugin_order = 2
    # 可使用的用户级别
    auth_level = 2

    # 事件管理器
    event: EventManager = None

    # 私有属性
    _enabled = False
    _onlyonce = False
    _notify_sys = False
    _notify = False
    _clean = False
    _cron = ''
    _failed_threshold = ''
    _sign_sites = []
    _domain_state_list = {}
    _check_state_failures_domain = []
    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        self.sites = SitesHelper()
        self.siteoper = SiteOper()
        self.event = EventManager()
        self.db_oper = DbOper()
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        self.sitechain = SiteChain()

        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._notify_sys = config.get("notify_sys")
            self._notify = config.get("notify")
            self._clean = config.get("clean")
            self._cron = config.get("cron")
            self._failed_threshold = config.get("failed_threshold")
            self._sign_sites = config.get("sign_sites")
            self._domain_state_list = config.get("domain_state_list") or {}

            # 过滤掉已删除的站点，排除未启用站点
            all_sites = [site.id for site in self.siteoper.list_active()] + [site.get("id") for site in self.__custom_sites()]
            self._sign_sites = [site_id for site_id in all_sites if site_id in self._sign_sites]

            if self._clean:
                self._domain_state_list = {}
                self._clean = False
                self.__update_config()
                log_path = settings.LOG_PATH / Path("plugins") / f"autodomainstate.log"
                if not log_path.exists():
                    logger.debug(f"插件自身日志文件不存在，日志未清理！")
                log_data = []
                with open(log_path, 'w', encoding='utf-8') as file:
                    file.writelines(log_data)
                logger.info('插件自身日志、暂存记录 已处理。')

            if self._enabled or self._onlyonce:
                if self._onlyonce:
                    logger.info(f"监测站点访问状态提醒 服务启动，立即运行一次")
                    self._scheduler.add_job(self.__runOnlyonce, 'date',
                                            run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                            name="立即运行一次 监测站点访问状态提醒")
                    self._onlyonce = False
                    self.__update_config()
                # 周期运行
                if self._enabled:
                    try:
                        cron = '0 0 * * *'
                        if self._cron:
                            cron = self._cron
                        self._scheduler.add_job(func=self.__runOnlyonce,
                                                trigger=CronTrigger.from_crontab(cron),
                                                name="监测站点访问状态提醒")
                    except Exception as err:
                        logger.error(f"定时任务配置错误：{err}")
                        # 推送实时消息
                        self.systemmessage.put(f"监测站点访问状态提醒 执行周期配置错误：{err}")

            # 保存配置
            self.__update_config()

            # 启动定时任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    def __update_config(self):
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "notify_sys": self._notify_sys,
            "notify": self._notify,
            "clean": self._clean,
            "cron": self._cron,
            "sign_sites": self._sign_sites,
            "domain_state_list": self._domain_state_list,
            "failed_threshold": self._failed_threshold
        })

    def __runOnlyonce(self, event: Event = None):
        """
        构建 站点访问状态 的结果数据
        """
        customSites = self.__custom_sites()
        site_all_options = ([{"domain": site.domain, "id": site.id, "name":site.name}
                         for site in self.siteoper.list_active()]
                        + [{"domain": site.get("domain"), "id": site.get("id"), "name": site.get("name")}
                           for site in customSites])
        _sign_sites_domain = []
        # 定义任务参数列表
        task_args = []
        for options in site_all_options:
            if options["id"] in self._sign_sites:
                task_args.append(options["domain"])
        # 执行任务并获取结果集合
        all_results = self._run_concurrent_tasks(
            task_func=self.__GetStateAndSendMassage,
            task_args_list=task_args,
            max_workers=20,
            timeout=20
        )
        # 解析结果
        for item in all_results:
            if item["error"]:
                logger.info(f"Failed: {item['arg']} -> {item['error']}")
            else:
                # logger.info(f"Success: {item['arg']} -> {item['result']}")
                domian_state, lst_state = item['result']
                if domian_state:
                    self.__update_domain_state_list(domain=item['arg'], site_state_data=domian_state)
        self.__update_config()
        # 检查站点失败总次数
        _check_state_failures_domain = []
        _sign_sites_domain = task_args
        for domain in self._domain_state_list.keys():
            _check_state_failures_domain = self.__check_state_failures(domain, _check_state_failures_domain, _sign_sites_domain)
        # logger.info(f"记录中的失败状态次数达到阀值站点域名列表：{_check_state_failures_domain}")
        if len(_check_state_failures_domain) > 0:
            _check_state_failures_name = []
            for options in site_all_options:
                if options["domain"] in _check_state_failures_domain:
                    _check_state_failures_name.append(options["name"])
            logger.info(f"近期连续访问失败次数到达阀值的 站点：{_check_state_failures_name} 对应域名：{_check_state_failures_domain}")
            if self._notify:
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title=f"【监测站点访问状态插件提醒】",
                    text=f"近期连续访问失败次数到达阀值的 站点：{_check_state_failures_name} 对应域名：{_check_state_failures_domain}"
                    )
            if self._notify_sys:
                self.systemmessage.put(f"近期连续访问失败次数到达阀值的 站点：{_check_state_failures_name} 对应域名：{_check_state_failures_domain}")
            if event:
                self.post_message(
                    channel=event.event_data.get("channel"),
                    title=f"【监测站点访问状态插件提醒】",
                    userid=event.event_data.get("userid")
                    )
        else:
            logger.info(f"未检测到 近期连续访问失败次数到达阀值的站点")

    def __update_domain_state_list(self, domain, site_state_data):
        """
        保留最新的指定次数的记录
        """
        if domain not in self._domain_state_list:
            self._domain_state_list[domain] = []
        self._domain_state_list[domain].append(site_state_data)
        # 指定次数
        max_records = max(1, int(self._failed_threshold)) if self._failed_threshold else 5
        if len(self._domain_state_list[domain]) > max_records:
            self._domain_state_list[domain] = self._domain_state_list[domain][-max_records:]

    def __check_state_failures(self, domain, _check_state_failures_domain, _sign_sites_domain):
        """
        单站访问失败次数阀值
        """
        if domain in self._domain_state_list:
            total_failures = sum(1 for state in self._domain_state_list[domain] if state["lst_state"] == 1)
            failed_threshold = max(1, int(self._failed_threshold)) if self._failed_threshold else 5
            if total_failures >= int(failed_threshold) and domain not in _check_state_failures_domain and domain in _sign_sites_domain:
                _check_state_failures_domain.append(domain)
        return _check_state_failures_domain

    def __GetStateAndSendMassage(self, domain: str):
        """
        获取站点访问状态
        """
        test_state, test_message =  self.sitechain.test(domain)
        lst_mod_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if test_message:
            lst_test_message = f"{test_message}"
        else:
            lst_test_message = f"没有返回信息"
        if test_state:
            lst_state = 0
            domian_state = {
                # 站点
                "domain": domain,
                # 最后测试访问状态 0-成功 1-失败
                "lst_state": lst_state,
                # 最后测试访问时间
                "lst_mod_date": lst_mod_date,
                # 最后测试访问返回的信息
                "lst_test_message": lst_test_message
            }
            return domian_state, lst_state
        else:
            lst_state = 1
            logger.info(f"当前测试站点连接性结果 {domain}：{lst_state} , {lst_test_message}")
            domian_state = {
                # 站点
                "domain": domain,
                # 最后测试访问状态 0-成功 1-失败
                "lst_state": lst_state,
                # 最后测试访问时间
                "lst_mod_date": lst_mod_date,
                # 最后测试访问返回的信息
                "lst_test_message": lst_test_message
            }
            return domian_state, lst_state

    def __custom_sites(self) -> List[Any]:
        custom_sites = []
        custom_sites_config = self.get_config("CustomSites")
        if custom_sites_config and custom_sites_config.get("enabled"):
            custom_sites = custom_sites_config.get("sites")
        return custom_sites

    def __remove_site_id(self, do_sites, site_id):
        if do_sites:
            if isinstance(do_sites, str):
                do_sites = [do_sites]

            # 删除对应站点
            if site_id:
                do_sites = [site for site in do_sites if int(site) != int(site_id)]
            else:
                # 清空
                do_sites = []

            # 若无站点，则停止
            if len(do_sites) == 0:
                self._enabled = False

        return do_sites

    def _run_concurrent_tasks(self, task_func, task_args_list: List[Any], max_workers: int = 50, timeout: int = 20) -> List[Dict]:
        """
        通用多线程任务执行函数（返回按任务参数顺序排列的结果列表）
        :param task_func: 需要并行执行的任务函数
        :param task_args_list: 任务参数列表（每个元素对应任务函数的一个参数）
        :param max_workers: 最大线程数（默认50）
        :return: 包含所有任务结果的列表，格式为 [{"arg": arg, "result": data, "error": None}, ...]
        """
        results = [None] * len(task_args_list)  # 初始化占位列表
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交任务并记录索引
            future_to_index = {
                executor.submit(task_func, arg): idx
                for idx, arg in enumerate(task_args_list)
            }
            # 处理结果
            for future in concurrent.futures.as_completed(future_to_index):
                idx = future_to_index[future]
                arg = task_args_list[idx]
                try:
                    result = future.result(timeout=timeout)
                    results[idx] = {"arg": arg, "result": result, "error": None}
                except Exception as e:
                    results[idx] = {"arg": arg, "result": None, "error": str(e)}
        return results

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        # 站点的可选项（内置站点 + 自定义站点）(排除未启用站点)
        customSites = self.__custom_sites()

        site_options = ([{"title": site.name, "value": site.id}
                         for site in self.siteoper.list_active()]
                        + [{"title": site.get("name"), "value": site.get("id")}
                           for site in customSites])
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
                                    'md': 2
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
                                    'md': 2
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify_sys',
                                            'label': '系统通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 2
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '渠道通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
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
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'clean',
                                            'label': '清理暂存结果、日志',
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
                                    'md': 8
                                },
                                'content': [
                                    {
                                        'component': 'VCronField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式，留空则自动每天凌晨12：00时执行一次'
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
                                            'model': 'failed_threshold',
                                            'label': '单站访问失败次数阀值',
                                            'placeholder': '留空则自动默认为5次'
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
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'chips': True,
                                            'multiple': True,
                                            'model': 'sign_sites',
                                            'label': '监测站点',
                                            'items': site_options
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
                                            'text': '插件每次运行都会测试选定站点的连接性状态，并且迭代暂存最新检测结果。插件会根据每各个站点暂存的数据综合判断：如果选定站点 记录的访问失败总次数 超过或等于设定的阀值,则会发出指定通知提醒。'
                                        }
                                    }
                                ]
                            },
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
                                            'text': '如果启用立即运行一次，会全量测试所选站点的连接性状态，需要点时间，日志刷新可查看检测结果。'
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
            'notify_sys': False,
            'notify': False,
            'clean': False,
            'cron': '',
            'failed_threshold': '',
            "sign_sites": []
        }

    @eventmanager.register(EventType.SiteDeleted)
    def site_deleted(self, event):
        """
        删除对应站点选中
        """
        site_id = event.event_data.get("site_id")
        config = self.get_config()
        if config:
            self._sign_sites = self.__remove_site_id(config.get("sign_sites") or [], site_id)
            # 保存配置
            self.__update_config()

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        pass

    def stop_service(self):
        """
        退出插件
        """
        # pass
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))
