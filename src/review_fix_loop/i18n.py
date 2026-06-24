from __future__ import annotations

import os

from .errors import ConfigError

DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = {"en", "zh-CN"}
LOCALE_ENV = "REVIEW_FIX_LOOP_LOCALE"

ZH_CN_MESSAGES = {
    "--pass > 1 requires --previous-run-record": "--pass 大于 1 时必须提供 --previous-run-record",
    "effective config hash differs from snapshot config_hash; create a fresh snapshot": (
        "当前有效配置 hash 与 snapshot config_hash 不一致；请重新生成 fresh snapshot"
    ),
    "rule file hashes differ from snapshot rule_hashes; create a fresh snapshot": (
        "规则文件 hash 与 snapshot rule_hashes 不一致；请重新生成 fresh snapshot"
    ),
    "working tree changed since snapshot; create a fresh snapshot": (
        "工作区已在 snapshot 后变化；请重新生成 fresh snapshot"
    ),
}


def resolve_locale(cli_locale: str | None) -> str:
    locale = cli_locale or os.environ.get(LOCALE_ENV) or DEFAULT_LOCALE
    if locale not in SUPPORTED_LOCALES:
        supported = ", ".join(sorted(SUPPORTED_LOCALES))
        raise ConfigError(f"unsupported locale: {locale} (supported: {supported})")
    return locale


def fallback_locale() -> str:
    locale = os.environ.get(LOCALE_ENV) or DEFAULT_LOCALE
    return locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE


def translate_message(message: str, locale: str) -> str:
    if locale != "zh-CN":
        return message
    return ZH_CN_MESSAGES.get(message, message)
