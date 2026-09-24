#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from generator import ContractError, generate_package


def _safe_failure(exc: Exception) -> tuple[str, str]:
    """Classify failures without echoing provider payloads, headers or secrets."""
    if isinstance(exc, ContractError):
        text = str(exc)
        if "质量门" in text:
            return "QUALITY", text
        if "配置" in text or "profile" in text or "环境变量" in text:
            return "CONFIG", text
        return "INPUT", text
    if isinstance(exc, ImportError):
        return "DEPENDENCY", "缺少文档解析依赖；请运行 python -m pip install -r requirements-import.txt"
    module = type(exc).__module__
    name = type(exc).__name__
    if module in ("llm_client", "phase4_content_generator") or name.startswith("LLM"):
        return "PROVIDER", "模型服务调用失败；请检查端点、模型、额度与网络后重试"
    if isinstance(exc, RuntimeError):
        return "IMPORT", "文档预处理失败；请检查 import-report.json 与本地输入后重试"
    if isinstance(exc, (OSError, ValueError)):
        return "RESOURCE", "学习包资源处理失败；请检查输入资源与输出目录后重试"
    return "INTERNAL", "生成失败；请保留失败质量报告并重试"


def main() -> int:
    parser = argparse.ArgumentParser(description="生成快考通单机学习包")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile", default="ruankao-xitixiangmu")
    parser.add_argument("--llm-config", type=Path)
    parser.add_argument("--open", action="store_true",
                        help="生成后自动启动或复用本地学习库，注册包并输出可打开的地址")
    parser.add_argument("--library", type=Path, default=Path.home() / ".quick-pass-study",
                        help="本地作答与错题数据目录；默认 ~/.quick-pass-study")
    parser.add_argument("--port", type=int, default=8766, help="本地学习库端口；默认 8766")
    parser.add_argument("--resume-agent-contract", action="store_true",
                        help="导入已由 Agent 回填的文档中间契约；校验源文件哈希，PDF 另校验物理页码后写 questions.json")
    parser.add_argument(
        "--import-only", action="store_true",
        help="首次生成 Agent handoff；配合 --resume-agent-contract 校验回填内容并输出 questions.json",
    )
    parser.add_argument("--fixture", action="store_true", help="只用于固定样本/渲染验证，不调用 LLM")
    parser.add_argument(
        "--agent-content", action="store_true",
        help="校验并打包唯一支持的 quick-pass-agent-content-v2，不调用外部 LLM",
    )
    args = parser.parse_args()
    try:
        if args.open and args.import_only:
            raise ContractError("--open 只能用于已完成的学习包，不能与 --import-only 同用")
        if not 1 <= args.port <= 65535:
            raise ContractError("port 必须是 1..65535")
        if args.output.exists() and not (args.import_only and args.resume_agent_contract):
            raise ContractError("输出目录已存在，拒绝覆盖")
        source = args.input
        if source.suffix.lower() != ".json":
            if args.fixture or args.agent_content:
                flag = "--agent-content" if args.agent_content else "--fixture"
                raise ContractError(f"{flag} 仅接受已含 concepts 的 JSON；文档请先 --import-only")
            from importer import import_bank
            if not args.import_only:
                raise ContractError("文档输入必须先使用 --import-only 生成或续跑 Agent 中间契约")
            if args.llm_config is not None:
                raise ContractError("文档 --import-only 不接受 --llm-config；预处理路径不调用外部模型")
            path = import_bank(source, args.output,
                               resume_agent_contract=args.resume_agent_contract)
            print(path)
            return 0
        elif args.import_only:
            raise ContractError("JSON 已是结构化入口；--import-only 用于文档解析")
        path = generate_package(source, args.output, profile_name=args.profile,
                                llm_config=args.llm_config, fixture=args.fixture,
                                agent_content=args.agent_content)
    except Exception as exc:
        category, message = _safe_failure(exc)
        print(json.dumps({"status": "failed", "category": category, "message": message},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    print(path)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    quality_status = manifest.get("content_status", "review_required")
    quality_labels = {
        "review_required": "学习包已生成；知识卡片仍需内容审校，请查看质量报告后修订。",
        "limited": "学习包已生成；部分卡片存在已声明的内容或证据缺口。",
        "agent_reviewed": "学习包已生成；已记录 Agent 内容审校，程序未验证语义真实性。",
        "fixture": "演示学习包已生成；不代表真实资料生成或内容审校通过。",
    }
    print(quality_labels.get(quality_status, "请查看学习包质量报告。"), file=sys.stderr)
    if args.open:
        try:
            from study_server import ensure_server, package_url, register
            package_id, _ = register(args.library, path)
            ensure_server(args.library, args.port, require_cases=bool(manifest.get("case_count")))
            print(package_url(package_id, args.port))
        except Exception as exc:
            print(json.dumps({"status": "package_created_library_failed", "category": "SERVICE",
                              "message": str(exc), "package": str(path)}, ensure_ascii=False), file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
