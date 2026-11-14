import os

ORDER = ["cards", "preflop_table", "preflop", "clone_table", "topx_table", "state", "model", "ranges", "bot", "agent"]


def main():
    seen = set()
    imports, body = [], []
    for name in ORDER:
        for line in open(f"pokerbot/{name}.py"):
            if line.startswith("from ."):
                continue
            if line.startswith(("import ", "from ")):
                if line not in seen:
                    seen.add(line)
                    imports.append(line)
                continue
            body.append(line)
        body.append("\n")
    pass
    with open("bot.py", "w") as f:
        f.writelines(sorted(imports))
        f.write("\n")
        f.writelines(body)


if __name__ == "__main__":
    main()
