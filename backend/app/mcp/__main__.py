"""``python -m app.mcp knowledge|aftersales`` 启动对应 MCP Server。"""
import sys


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"knowledge", "aftersales"}:
        print("usage: python -m app.mcp {knowledge|aftersales}")
        raise SystemExit(2)

    if sys.argv[1] == "knowledge":
        from app.mcp.knowledge_server import main as run
    else:
        from app.mcp.aftersales_server import main as run
    run()


if __name__ == "__main__":
    main()
