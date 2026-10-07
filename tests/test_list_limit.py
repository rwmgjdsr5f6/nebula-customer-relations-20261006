"""crm.py list 子命令 --limit 条数限制的回归测试。

固定样例为两家公司三位合成联系人（按此顺序新增到全新数据库，编号以新增结果为准）：
- 星河科技：林宁（lin@example.test）
- 远帆咨询：周岚（zhou@example.test）
- 星河科技：许禾（xu@example.test）

验证的既有行为：
- 省略 --limit 返回全部匹配记录；--limit 作用于筛选后的结果，
  按编号升序截取，各字段原值不变；
- 限制条数大于匹配数时不补齐记录，无匹配时仍为空结果；
- 默认 JSON 与显式 --format json 均输出单个数组且内容一致；
  CSV 表头不计入条数，解析后的记录与顺序同 JSON 一致，无匹配时只有表头；
- 参数边界：首尾空白与前导零被接受（" 002 " 等价于 2），
  上限 9223372036854775807 合法；
- 空串、纯空白、0、负数、小数、字母、非 ASCII 数字及 9223372036854775808
  均退出 2，标准输出为空，标准错误仅为 limit: must be a positive integer 一行，
  不出现异常堆栈；无效限制指向尚不存在的数据库时不创建文件，
  有效限制查询同样的新路径则创建空库并返回空结果；
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

# 上限 9223372036854775807（2**63 - 1）合法，超过上限一即被拒绝
MAX_LIMIT_TEXT = "9223372036854775807"
OVER_MAX_LIMIT_TEXT = "9223372036854775808"

# 空串、纯空白、0、负数、小数、字母、非 ASCII 数字及超出上限的数值
INVALID_LIMITS = [
    "",
    "   ",
    "\t\t",
    " \t ",
    "0",
    "00",
    " 0 ",
    "-1",
    "-10",
    "1.5",
    "0.5",
    "-0.5",
    "2.",
    ".5",
    "abc",
    "2x",
    "x2",
    "1e3",
    "１２３",
    "２",
    "١٢٣",
    OVER_MAX_LIMIT_TEXT,
    "99999999999999999999999999",
]

CSV_HEADER = "id,name,email,company"


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

    def list_contacts(self, db_path, fmt=None, company=None, name=None,
                      email=None, limit=None):
        """执行 list；limit 为 None 时省略 --limit，空串等值仍原样传入。"""
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
        """在全新数据库依次新增三位联系人并返回新增记录。

        顺序为星河科技的林宁、远帆咨询的周岚、星河科技的许禾，
        编号以 add 返回值为准且严格升序、互不相同。
        """
        lin_ning = self.assert_add_success(
            self.add_contact(self.db_path, "林宁", LIN_EMAIL, COMPANY_XINGHE),
            {"name": "林宁", "email": LIN_EMAIL, "company": COMPANY_XINGHE},
        )
        zhou_lan = self.assert_add_success(
            self.add_contact(self.db_path, "周岚", ZHOU_EMAIL, COMPANY_YUANFAN),
            {"name": "周岚", "email": ZHOU_EMAIL, "company": COMPANY_YUANFAN},
        )
        xu_he = self.assert_add_success(
            self.add_contact(self.db_path, "许禾", XU_EMAIL, COMPANY_XINGHE),
            {"name": "许禾", "email": XU_EMAIL, "company": COMPANY_XINGHE},
        )

        ids = [r["id"] for r in (lin_ning, zhou_lan, xu_he)]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), 3)
        return lin_ning, zhou_lan, xu_he

    def list_records(self, db_path, **kwargs):
        """执行 list，断言成功后返回解析后的 JSON 记录列表。"""
        result = self.list_contacts(db_path, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertIsInstance(records, list)
        return records

    def assert_list_success(self, db_path, expected_records, **kwargs):
        """断言 list 成功：退出码 0、无标准错误，记录（含顺序）与预期一致。"""
        records = self.list_records(db_path, **kwargs)
        self.assertEqual(records, expected_records)
        self.assertEqual([r["id"] for r in records],
                         sorted(r["id"] for r in records))
        for record in records:
            self.assertEqual(set(record.keys()),
                             {"id", "name", "email", "company"})
        return records

    def assert_limit_rejected(self, result):
        """断言 limit 被拒绝：退出码 2、无标准输出、标准错误恰为单行、无堆栈。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        stderr_text = result.stderr.decode("utf-8")
        self.assertEqual(stderr_text, LIMIT_ERROR_LINE + "\n")
        self.assertNotIn("Traceback", stderr_text)

    def parse_csv(self, raw_text):
        """按 CSV 规则解析标准输出。"""
        return list(csv.reader(io.StringIO(raw_text)))

    def assert_records_intact(self, expected_records):
        """用不带限制的 list 核对记录内容、编号与顺序完整保留。"""
        records = self.list_records(self.db_path)
        self.assertEqual(records, expected_records)
        self.assertEqual(
            [r["id"] for r in records],
            [r["id"] for r in expected_records],
        )

    # ---- 省略与指定 --limit 的成功查询行为 ----

    def test_list_without_limit_returns_all_records(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        expected = [lin_ning, zhou_lan, xu_he]

        records = self.assert_list_success(self.db_path, expected)
        # 三条完整记录按编号升序，各字段与新增结果逐字一致
        self.assertEqual(
            [r["id"] for r in records],
            [lin_ning["id"], zhou_lan["id"], xu_he["id"]],
        )
        for record, added in zip(records, expected):
            self.assertEqual(record, added)

        self.assert_records_intact(expected)

    def test_limit_two_cross_company_returns_first_two(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()

        # 跨公司 --limit 2：按编号升序截取前两条，即林宁与周岚
        records = self.assert_list_success(
            self.db_path, [lin_ning, zhou_lan], limit="2"
        )
        self.assertEqual(
            [r["id"] for r in records], [lin_ning["id"], zhou_lan["id"]]
        )
        self.assertNotIn(xu_he["id"], [r["id"] for r in records])

        self.assert_records_intact([lin_ning, zhou_lan, xu_he])

    def test_limit_applies_after_company_filter(self):
        lin_ning, _zhou_lan, xu_he = self.seed_contacts()

        # 公司筛选为星河科技且限制为 2：返回林宁与许禾，
        # 证明限制作用于筛选后的结果而非全表前两条
        records = self.assert_list_success(
            self.db_path, [lin_ning, xu_he],
            company=COMPANY_XINGHE, limit="2",
        )
        self.assertEqual(
            [r["id"] for r in records], [lin_ning["id"], xu_he["id"]]
        )
        self.assertEqual(
            {r["company"] for r in records}, {COMPANY_XINGHE}
        )

        self.assert_records_intact([lin_ning, _zhou_lan, xu_he])

    def test_limit_one_with_name_filter(self):
        _lin_ning, _zhou_lan, xu_he = self.seed_contacts()

        # 姓名筛选为许、限制为 1：只返回许禾
        records = self.assert_list_success(
            self.db_path, [xu_he], name="许", limit="1"
        )
        self.assertEqual(records[0]["name"], "许禾")

        self.assert_records_intact([_lin_ning, _zhou_lan, xu_he])

    def test_limit_one_with_email_filter(self):
        _lin_ning, _zhou_lan, xu_he = self.seed_contacts()

        # 完整邮箱筛选为 xu@example.test、限制为 1：只返回许禾
        records = self.assert_list_success(
            self.db_path, [xu_he], email=XU_EMAIL, limit="1"
        )
        self.assertEqual(records[0]["email"], XU_EMAIL)

        self.assert_records_intact([_lin_ning, _zhou_lan, xu_he])

    def test_limit_larger_than_match_count_does_not_pad(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        expected = [lin_ning, zhou_lan, xu_he]

        # 限制为 10 时只返回实际匹配的三条，不补齐记录
        records = self.assert_list_success(self.db_path, expected, limit="10")
        self.assertEqual(len(records), 3)

        # 公司筛选后匹配两条，限制 10 仍只返回两条
        self.assert_list_success(
            self.db_path, [lin_ning, xu_he],
            company=COMPANY_XINGHE, limit="10",
        )

        self.assert_records_intact(expected)

    def test_limit_with_no_match_returns_empty(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        expected = [lin_ning, zhou_lan, xu_he]

        # 无匹配的姓名、公司、邮箱筛选在限制下仍为空结果
        self.assert_list_success(self.db_path, [], name="不存在", limit="2")
        self.assert_list_success(self.db_path, [], company="不存在公司", limit="2")
        self.assert_list_success(
            self.db_path, [], email="nobody@example.test", limit="2"
        )

        self.assert_records_intact(expected)

    # ---- 输出格式 ----

    def test_default_and_explicit_json_are_single_identical_arrays(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()

        omitted = self.list_contacts(self.db_path, limit="2")
        explicit = self.list_contacts(self.db_path, fmt="json", limit="2")
        self.assertEqual(omitted.returncode, 0, omitted.stderr.decode("utf-8"))
        self.assertEqual(explicit.returncode, 0, explicit.stderr.decode("utf-8"))
        self.assertEqual(omitted.stderr, b"")
        self.assertEqual(explicit.stderr, b"")
        # 默认 JSON 与显式 json 的标准输出逐字节相同
        self.assertEqual(omitted.stdout, explicit.stdout)

        # 输出为单个 JSON 数组，内容恰为前两条记录
        records = json.loads(omitted.stdout.decode("utf-8"))
        self.assertIsInstance(records, list)
        self.assertEqual(records, [lin_ning, zhou_lan])

        self.assert_records_intact([lin_ning, zhou_lan, xu_he])

    def test_csv_limit_matches_json_and_header_not_counted(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        expected = [lin_ning, zhou_lan]

        csv_result = self.list_contacts(self.db_path, fmt="csv", limit="2")
        json_result = self.list_contacts(self.db_path, fmt="json", limit="2")
        self.assertEqual(csv_result.returncode, 0, csv_result.stderr.decode("utf-8"))
        self.assertEqual(json_result.returncode, 0, json_result.stderr.decode("utf-8"))
        self.assertEqual(csv_result.stderr, b"")
        self.assertEqual(json_result.stderr, b"")

        rows = self.parse_csv(csv_result.stdout.decode("utf-8"))
        json_records = json.loads(json_result.stdout.decode("utf-8"))
        self.assertEqual(json_records, expected)

        # 表头固定且不计入条数：限制 2 时恰为表头加两条数据行
        self.assertEqual(rows[0], CSV_HEADER.split(","))
        data_rows = rows[1:]
        self.assertEqual(len(data_rows), 2)

        # 解析后的记录与顺序同 JSON 一致
        for row, record in zip(data_rows, json_records):
            self.assertEqual(
                row,
                [
                    str(record["id"]),
                    record["name"],
                    record["email"],
                    record["company"],
                ],
            )
        self.assertEqual(
            [row[0] for row in data_rows],
            [str(r["id"]) for r in expected],
        )

        # 无匹配时 CSV 只有现有表头一行
        no_match = self.list_contacts(
            self.db_path, fmt="csv", name="不存在", limit="2"
        )
        self.assertEqual(no_match.returncode, 0, no_match.stderr.decode("utf-8"))
        self.assertEqual(no_match.stderr, b"")
        self.assertEqual(
            no_match.stdout.decode("utf-8"), CSV_HEADER + "\r\n"
        )

        self.assert_records_intact([lin_ning, zhou_lan, xu_he])

    # ---- 参数边界 ----

    def test_limit_with_whitespace_and_leading_zeros(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        expected_two = [lin_ning, zhou_lan]

        # 带首尾空白和前导零的 " 002 " 与 2 结果相同
        for limit in (" 002 ", "002", "02", " 2 ", "\t2\t", " 002", "002 "):
            with self.subTest(limit=limit):
                self.assert_list_success(
                    self.db_path, expected_two, limit=limit
                )

        # 前导零不影响公司筛选后的截取
        self.assert_list_success(
            self.db_path, [lin_ning, xu_he],
            company=COMPANY_XINGHE, limit=" 002 ",
        )

        self.assert_records_intact([lin_ning, zhou_lan, xu_he])

    def test_limit_max_int64_is_valid(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        expected = [lin_ning, zhou_lan, xu_he]

        # 上限 9223372036854775807 合法，返回全部匹配记录
        self.assert_list_success(self.db_path, expected, limit=MAX_LIMIT_TEXT)
        self.assert_list_success(
            self.db_path, [lin_ning, xu_he],
            company=COMPANY_XINGHE, limit=MAX_LIMIT_TEXT,
        )

        self.assert_records_intact(expected)

    def test_invalid_limits_are_rejected(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()

        # 其他参数保持有效（公司筛选与格式均合法），唯一问题是 limit
        for limit in INVALID_LIMITS:
            with self.subTest(limit=limit):
                result = self.list_contacts(
                    self.db_path,
                    company=COMPANY_XINGHE,
                    fmt="json",
                    limit=limit,
                )
                self.assert_limit_rejected(result)

        # 不带其他筛选条件时同样被拒绝
        for limit in ("", "0", "-1", "1.5", "abc", "１２３", OVER_MAX_LIMIT_TEXT):
            with self.subTest(limit=limit):
                result = self.list_contacts(self.db_path, limit=limit)
                self.assert_limit_rejected(result)

        self.assert_records_intact([lin_ning, zhou_lan, xu_he])

    # ---- 不存在的数据库 ----

    def test_invalid_limit_does_not_create_missing_database(self):
        fresh_db = self.tmpdir / "fresh-limit.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 无效限制在连接数据库前失败：文件及任何 SQLite 伴随文件都不应出现
        for index, limit in enumerate(("", "0", "-1", "abc", OVER_MAX_LIMIT_TEXT)):
            with self.subTest(limit=limit):
                result = self.list_contacts(fresh_db, limit=limit)
                self.assert_limit_rejected(result)
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

        # 有效限制查询同样的新路径：创建空库并返回空结果
        result = self.list_contacts(fresh_db, limit="2")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), [])
        self.assertTrue(fresh_db.exists())

        # 不带限制再次查询仍为空数组
        again = self.list_contacts(fresh_db)
        self.assertEqual(again.returncode, 0, again.stderr.decode("utf-8"))
        self.assertEqual(again.stderr, b"")
        self.assertEqual(json.loads(again.stdout.decode("utf-8")), [])

    # ---- 查询对已有数据的影响 ----

    def test_success_and_failed_limit_queries_leave_records_unchanged(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        expected = [lin_ning, zhou_lan, xu_he]

        # 成功的受限查询：跨公司、公司筛选、姓名、邮箱、CSV、无命中
        successful = [
            {"limit": "1"},
            {"limit": "2"},
            {"limit": "10"},
            {"company": COMPANY_XINGHE, "limit": "2"},
            {"name": "许", "limit": "1"},
            {"email": XU_EMAIL, "limit": "1"},
            {"fmt": "csv", "limit": "2"},
            {"name": "不存在", "limit": "2"},
            {"limit": MAX_LIMIT_TEXT},
        ]
        for kwargs in successful:
            with self.subTest(kwargs=kwargs):
                result = self.list_contacts(self.db_path, **kwargs)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
                self.assertEqual(result.stderr, b"")

        # 成功的受限查询之后：记录完整保留
        self.assert_records_intact(expected)

        # 失败的受限查询：各类无效 limit
        for limit in INVALID_LIMITS:
            with self.subTest(limit=limit):
                result = self.list_contacts(self.db_path, limit=limit)
                self.assert_limit_rejected(result)

        # 失败的受限查询之后：记录内容、编号与顺序仍完整保留
        self.assert_records_intact(expected)


if __name__ == "__main__":
    unittest.main()
