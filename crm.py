#!/usr/bin/env python3
"""本地客户关系管理台命令行入口。

仅支持两个行为：
- add:  新增联系人
- list: 按公司名精确筛选联系人

数据持久化在通过 --db 指定的 SQLite 数据库文件中，
文件不存在时自动初始化，已存在则复用。
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    company TEXT NOT NULL
)
"""


def fail(field, message):
    """输出字段错误到标准错误并以退出码 2 结束。"""
    print(f"{field}: {message}", file=sys.stderr)
    sys.exit(2)


def clean(value):
    """清理首尾空白，保留内部字符与大小写。"""
    return value.strip()


def valid_email(email):
    """邮箱规则：恰好一个 @、两侧非空、域名至少含一个点且各段非空、无空白。"""
    if any(ch.isspace() for ch in email):
        return False
    if email.count("@") != 1:
        return False
    local, _, domain = email.partition("@")
    if not local or not domain:
        return False
    parts = domain.split(".")
    if len(parts) < 2 or any(not part for part in parts):
        return False
    return True


def connect_db(db_path):
    """父目录存在时连接数据库，初始化缺失的表；复用已有数据库。"""
    if not Path(db_path).parent.is_dir():
        fail("db", "parent directory does not exist")
    conn = sqlite3.connect(db_path)
    conn.execute(CREATE_TABLE_SQL)
    conn.commit()
    return conn


def cmd_add(args):
    name = clean(args.name)
    email = clean(args.email)
    company = clean(args.company)

    if not name:
        fail("name", "must not be empty")
    if not valid_email(email):
        fail("email", "invalid email address")
    if not company:
        fail("company", "must not be empty")

    conn = connect_db(args.db)
    try:
        cursor = conn.execute(
            "INSERT INTO contacts (name, email, company) VALUES (?, ?, ?)",
            (name, email, company),
        )
        conn.commit()
    finally:
        conn.close()

    record = {
        "id": cursor.lastrowid,
        "name": name,
        "email": email,
        "company": company,
    }
    print(json.dumps(record, ensure_ascii=False))
    return 0


def cmd_list(args):
    company = clean(args.company)
    if not company:
        fail("company", "must not be empty")

    conn = connect_db(args.db)
    try:
        rows = conn.execute(
            "SELECT id, name, email, company "
            "FROM contacts WHERE company = ? ORDER BY id ASC",
            (company,),
        ).fetchall()
    finally:
        conn.close()

    records = [
        {"id": row[0], "name": row[1], "email": row[2], "company": row[3]}
        for row in rows
    ]
    print(json.dumps(records, ensure_ascii=False))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="crm", description="本地客户关系管理台")
    parser.add_argument("--db", required=True, help="SQLite 数据库文件路径")

    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_add = subparsers.add_parser("add", help="新增联系人")
    parser_add.add_argument("--name", required=True, help="姓名")
    parser_add.add_argument("--email", required=True, help="邮箱")
    parser_add.add_argument("--company", required=True, help="公司名")
    parser_add.set_defaults(func=cmd_add)

    parser_list = subparsers.add_parser("list", help="按公司筛选联系人")
    parser_list.add_argument("--company", required=True, help="公司名")
    parser_list.set_defaults(func=cmd_list)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
