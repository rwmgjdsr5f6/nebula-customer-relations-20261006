"""crm.py list 子命令 --limit 条数限制的回归测试。

固定样例为两家公司三位合成联系人（按此顺序新增到全新数据库，编号以新增结果为准）：
- 星河科技：林宁（lin@example.test）
- 远帆咨询：周岚（zhou@example.test）
- 星河科技：许禾（xu@example.test）

验证的既有行为：
- 省略 --limit 返回全部匹配记录；--limit 作用于筛选后的结果，
  按编号升序截取，各字段原值不变；
- 限制大于匹配条数时不补齐记录，无匹配时仍为空结果；
- 默认 JSON 与显式 --format json 均输出单个数组且内容一致；
  CSV 表头不计入条数，解析后的记录与顺序同 JSON 一致，无匹配时只有表头；
- 限制值允许首尾空白与前导零（" 002 " 与 2 等价），
  上限 9223372036854775807 合法并返回全部匹配记录；
- 空串、纯空白、0、负数、小数、字母、非 ASCII 数字及 9223372036854775808
  均退出码 2、标准输出为空、标准错误仅一行 limit: must be a positive integer，
  不出现异常堆栈，且不创建尚不存在的数据库文件；
- 父目录存在而数据库文件不存在时，合法限制的 list 创建空库并返回空结果；
- 每组成功或失败查询之后，不带限制的 list 核对记录内容、编号与顺序完整保留。

仅使用 Python 3 标准库 unittest，每次查询都启动新的 crm.py 子进程，
所有样例数据都放在独立的临时目录中，测试结束后自动清理；重复执行结果一致，
不依赖网络或任何第三方库。
在项目根目录运行：python -m unittest discover -s tests
"""

import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CRM_SCRIPT = PROJECT_ROOT / "crm.py"

COMPANY_XINGHE = "星河科技"
COMPANY_YUANFAN = "远帆咨询"
LIN_EMAIL = "lin@example.test"
ZHOU_EMAIL = "zhou@example.test"
XU_EMAIL = "xu@example.test"

LIMIT_ERROR_LINE = "limit: must be a positive integer"
CSV_HEADER = ["id", "name", "email", "company"]

# 固定样例：按新增顺序排列的 (姓名, 邮箱, 公司)
SAMPLE_CONTACTS = [
    ("林宁", LIN_EMAIL, COMPANY_XINGHE),
    ("周岚", ZHOU_EMAIL, COMPANY_YUANFAN),
    ("许禾", XU_EMAIL, COMPANY_XINGHE),
]

# 应被拒绝的限制值：空串、纯空白、0、负数、小数、字母、
# 非 ASCII 数字（全角数字、阿拉伯-印度数字）以及超出 64 位有符号整数上限
INVALID_LIMITS = [
    "",
    "   ",
    " \t ",
    "0",
    " 000 ",
    "-1",
    "-9223372036854775808",
    "1.5",
    "2.0",
    "abc",
    "2条",
    "２",
    "１２",
    "٢",
    "9223372036854775808",
    "99999999999999999999999999",
]


class ListLimitTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.tmpdir = Path(self._tmpdir.name)
        self.db_path = self.tmpdir / "contacts.sqlite3"

    def run_crm(self, db_path, *cli_args):
        """运行 crm.py 子进程并返回完整结果。"""
        return subprocess.run(
            [sys.executable, str(CRM_SCRIPT), "--db", str(db_path), *cli_args],
            capture_output=True,
        )

    def add_contact(self, db_path, name, email, company):
        return self.run_crm(
            db_path, "add", "--name", name, "--email", email, "--company", company
        )

    def list_contacts(self, db_path, company=None, name=None, email=None,
                      fmt=None, limit=None):
        """执行 list，仅组装非 None 的筛选、格式与限制参数。"""
        cli_args = ["list"]
        if company is not None:
            cli_args.extend(["--company", company])
        if name is not None:
            cli_args.extend(["--name", name])
        if email is not None:
            cli_args.extend(["--email", email])
        if fmt is not None:
            cli_args.extend(["--format", fmt])
        if limit is not None:
            cli_args.extend(["--limit", limit])
        return self.run_crm(db_path, *cli_args)

    def assert_add_success(self, result, expected):
        """断言新增成功并返回解析后的联系人字典。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
        self.assertIsInstance(record["id"], int)
        self.assertEqual(record["name"], expected["name"])
        self.assertEqual(record["email"], expected["email"])
        self.assertEqual(record["company"], expected["company"])
        return record

    def seed_contacts(self):
        """按固定顺序新增三位联系人，返回以 add 输出为准的记录列表。"""
        records = []
        for name, email, company in SAMPLE_CONTACTS:
            result = self.add_contact(self.db_path, name, email, company)
            records.append(
                self.assert_add_success(
                    result, {"name": name, "email": email, "company": company}
                )
            )
        return records

    def assert_json_list_success(self, db_path, expected_records, **kwargs):
        """断言 JSON list 成功：退出码 0、标准错误为空、输出单个数组，
        记录（含顺序与各字段原值）与期望完全一致。"""
        result = self.list_contacts(db_path, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(records, list)
        self.assertEqual(records, expected_records)
        return records

    def parse_csv_records(self, raw_stdout):
        """解析 CSV 标准输出，返回 (表头, 记录字典列表)，编号还原为整数。"""
        text = raw_stdout.decode("utf-8")
        rows = list(csv.reader(io.StringIO(text)))
        header, data_rows = rows[0], rows[1:]
        records = [
            {"id": int(row[0]), "name": row[1], "email": row[2], "company": row[3]}
            for row in data_rows
        ]
        return header, records

    def assert_csv_list_success(self, db_path, expected_records, **kwargs):
        """断言 CSV list 成功：表头固定且不计入条数，
        解析后的记录与顺序同期望一致。"""
        result = self.list_contacts(db_path, fmt="csv", **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        header, records = self.parse_csv_records(result.stdout)
        self.assertEqual(header, CSV_HEADER)
        self.assertEqual(records, expected_records)
        return records

    def assert_records_intact(self, expected_records):
        """不带限制的 list 核对全部记录内容、编号与升序顺序完整保留。"""
        self.assert_json_list_success(self.db_path, expected_records)

    def assert_invalid_limit(self, db_path, limit, **kwargs):
        """断言非法限制：退出码 2、标准输出为空、
        标准错误仅一行 limit 错误且不包含异常堆栈。"""
        result = self.list_contacts(db_path, limit=limit, **kwargs)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        stderr_text = result.stderr.decode("utf-8")
        self.assertEqual(stderr_text, LIMIT_ERROR_LINE + "\n")
        self.assertNotIn("Traceback", stderr_text)

    # ---- 基本截取行为 ----

    def test_omit_limit_returns_all_matches(self):
        records = self.seed_contacts()
        self.assert_json_list_success(self.db_path, records)
        self.assert_json_list_success(self.db_path, records, fmt="json")
        self.assert_records_intact(records)

    def test_limit_two_cross_company(self):
        records = self.seed_contacts()
        self.assert_json_list_success(self.db_path, records[:2], limit="2")
        self.assert_records_intact(records)

    def test_limit_two_with_company_filter(self):
        """限制作用于筛选后的结果：星河科技内取前两条为林宁与许禾。"""
        records = self.seed_contacts()
        xinghe = [records[0], records[2]]
        self.assert_json_list_success(
            self.db_path, xinghe, company=COMPANY_XINGHE, limit="2"
        )
        self.assert_records_intact(records)

    def test_limit_one_with_name_filter(self):
        records = self.seed_contacts()
        self.assert_json_list_success(
            self.db_path, [records[2]], name="许", limit="1"
        )
        self.assert_records_intact(records)

    def test_limit_one_with_email_filter(self):
        records = self.seed_contacts()
        self.assert_json_list_success(
            self.db_path, [records[2]], email=XU_EMAIL, limit="1"
        )
        self.assert_records_intact(records)

    def test_limit_larger_than_matches_does_not_pad(self):
        records = self.seed_contacts()
        self.assert_json_list_success(self.db_path, records, limit="10")
        self.assert_records_intact(records)

    def test_limit_with_no_matches_returns_empty(self):
        records = self.seed_contacts()
        self.assert_json_list_success(
            self.db_path, [], company="不存在的公司", limit="2"
        )
        # CSV 无匹配时只有现有表头，表头不计入条数
        self.assert_csv_list_success(
            self.db_path, [], company="不存在的公司", limit="2"
        )
        self.assert_records_intact(records)

    def test_results_sorted_by_id_with_original_fields(self):
        """限制查询结果按编号升序，且各字段与 add 输出原值一致。"""
        records = self.seed_contacts()
        limited = self.assert_json_list_success(self.db_path, records[:2], limit="2")
        self.assertEqual([r["id"] for r in limited], sorted(r["id"] for r in limited))
        for actual, expected in zip(limited, records):
            self.assertEqual(actual, expected)
        self.assert_records_intact(records)

    # ---- 输出格式 ----

    def test_default_and_explicit_json_are_identical_arrays(self):
        records = self.seed_contacts()
        default_result = self.list_contacts(self.db_path, limit="2")
        explicit_result = self.list_contacts(self.db_path, fmt="json", limit="2")
        self.assertEqual(default_result.returncode, 0)
        self.assertEqual(explicit_result.returncode, 0)
        self.assertEqual(default_result.stdout, explicit_result.stdout)
        parsed = json.loads(default_result.stdout.decode("utf-8"))
        self.assertIsInstance(parsed, list)
        self.assertEqual(parsed, records[:2])
        self.assert_records_intact(records)

    def test_csv_matches_json_with_limit(self):
        """CSV 解析后的记录与顺序同 JSON 一致，表头不计入条数。"""
        records = self.seed_contacts()
        json_records = self.assert_json_list_success(
            self.db_path, records[:2], limit="2"
        )
        csv_records = self.assert_csv_list_success(
            self.db_path, records[:2], limit="2"
        )
        self.assertEqual(csv_records, json_records)
        self.assert_records_intact(records)

    # ---- 合法边界 ----

    def test_limit_with_surrounding_whitespace_and_leading_zeros(self):
        """" 002 " 与 2 的结果相同：首尾空白被清理，前导零被接受。"""
        records = self.seed_contacts()
        padded = self.assert_json_list_success(self.db_path, records[:2], limit=" 002 ")
        plain = self.assert_json_list_success(self.db_path, records[:2], limit="2")
        self.assertEqual(padded, plain)
        self.assert_records_intact(records)

    def test_limit_max_int64_returns_all_matches(self):
        records = self.seed_contacts()
        self.assert_json_list_success(
            self.db_path, records, limit="9223372036854775807"
        )
        self.assert_records_intact(records)

    # ---- 非法限制 ----

    def test_invalid_limits_rejected_on_populated_db(self):
        """各类非法限制均退出 2、标准输出为空、标准错误仅一行，
        其余参数保持有效也不影响判定。"""
        records = self.seed_contacts()
        for limit in INVALID_LIMITS:
            with self.subTest(limit=limit):
                self.assert_invalid_limit(self.db_path, limit)
                self.assert_invalid_limit(
                    self.db_path, limit, company=COMPANY_XINGHE, fmt="csv"
                )
                self.assert_invalid_limit(
                    self.db_path, limit, name="许", email=XU_EMAIL
                )
        self.assert_records_intact(records)

    def test_invalid_limit_does_not_create_missing_db(self):
        """非法限制指向尚不存在的数据库时不创建文件。"""
        missing_db = self.tmpdir / "missing.sqlite3"
        for limit in INVALID_LIMITS:
            with self.subTest(limit=limit):
                self.assert_invalid_limit(missing_db, limit)
                self.assertFalse(missing_db.exists())

    def test_valid_limit_creates_empty_db_with_empty_result(self):
        """合法限制查询同样的新路径则创建空库并返回空结果。"""
        missing_db = self.tmpdir / "empty.sqlite3"
        self.assertFalse(missing_db.exists())
        self.assert_json_list_success(missing_db, [], limit="2")
        self.assertTrue(missing_db.exists())
        # 上限值同样创建空库并返回空结果
        other_db = self.tmpdir / "empty_max.sqlite3"
        self.assert_json_list_success(
            other_db, [], limit="9223372036854775807"
        )
        self.assertTrue(other_db.exists())


if __name__ == "__main__":
    unittest.main()
