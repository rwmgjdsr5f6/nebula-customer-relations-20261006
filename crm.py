#!/usr/bin/env python3
"""本地客户关系管理台：联系人新增与按公司筛选。"""

import argparse
import json
import sqlite3
import sys

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    company TEXT NOT NULL
)
"""


def fail(field, message):
    print(f"错误：字段 {field} {message}", file=sys.stderr)
    sys.exit(2)


def valid_email(email):
    if not email or any(ch.isspace() for ch in email):
        return False
    if email.count("@") != 1:
        return False
    local, domain = email.split("@")
    if not local or not domain:
        return False
    if "." not in domain:
        return False
    if any(not part for part in domain.split(".")):
        return False
    return True


def open_db(path):
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    return conn


def cmd_add(args):
    name = args.name.strip()
    email = args.email.strip()
    company = args.company.strip()

    if not name:
        fail("name", "清理后不能为空")
    if not company:
        fail("company", "清理后不能为空")
    if not valid_email(email):
        fail("email", "格式不合法：需恰好一个 @，两侧非空，域名至少含一个点且各段非空，整串不得含空白字符")

    conn = open_db(args.db)
    with conn:
        cur = conn.execute(
            "INSERT INTO contacts (name, email, company) VALUES (?, ?, ?)",
            (name, email, company),
        )
        contact_id = cur.lastrowid
    conn.close()

    print(json.dumps(
        {"id": contact_id, "name": name, "email": email, "company": company},
        ensure_ascii=False,
    ))


def cmd_list(args):
    company = args.company.strip()
    if not company:
        fail("company", "清理后不能为空")

    conn = open_db(args.db)
    rows = conn.execute(
        "SELECT id, name, email, company FROM contacts WHERE company = ? ORDER BY id ASC",
        (company,),
    ).fetchall()
    conn.close()

    print(json.dumps(
        [{"id": r[0], "name": r[1], "email": r[2], "company": r[3]} for r in rows],
        ensure_ascii=False,
    ))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="crm.py", description="本地客户关系管理台")
    parser.add_argument("--db", default="crm.db", help="SQLite 数据库文件路径")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="新增联系人")
    add_parser.add_argument("--db", default=None, help=argparse.SUPPRESS)
    add_parser.add_argument("--name", required=True, help="姓名")
    add_parser.add_argument("--email", required=True, help="邮箱")
    add_parser.add_argument("--company", required=True, help="公司名")
    add_parser.set_defaults(func=cmd_add)

    list_parser = subparsers.add_parser("list", help="按公司筛选联系人")
    list_parser.add_argument("--db", default=None, help=argparse.SUPPRESS)
    list_parser.add_argument("--company", required=True, help="查询公司名")
    list_parser.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    # 允许 --db 出现在子命令前后，子命令处的取值优先
    args.db = args.db if isinstance(args.db, str) else "crm.db"
    args.func(args)


if __name__ == "__main__":
    main()
