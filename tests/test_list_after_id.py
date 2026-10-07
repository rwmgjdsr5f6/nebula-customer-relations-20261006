"""crm.py list 子命令 --after-id 续查光标的回归测试。

固定样例为两家公司三位合成联系人（按此顺序新增到全新数据库，编号以新增结果为准）：
- 星河科技：林宁（lin@example.test）编号 1
- 远帆咨询：周岚（zhou@example.test）编号 2
- 星河科技：许禾（xu@example.test）编号 3

验证的行为：
- 省略 --after-id 保持原行为（从首条开始）；指定后结果只包含 id 严格大于
  该值的记录，边界编号无需存在，联系人删除后该编号仍可作为边界；
- --after-id 与公司、姓名、邮箱条件取交集，先按编号升序，再应用 --limit；
- 默认 JSON 与 CSV 返回相同记录与顺序，保留现有字段、CSV 表头与 CRLF 转义，
  无匹配时 JSON 为 []、CSV 只有表头，不增加页码、总数或下一页字段；
- 参数边界：首尾空白与前导零被接受（" 001 " 等价于 1），
  上限 9223372036854775807 合法；
- 空串、纯空白、0、负数、小数、非 ASCII 数字及 9223372036854775808
  均退出 2，标准输出为空，标准错误仅为
  after-id: must be a positive integer 一行，不出现异常堆栈；
  无效值指向尚不存在的数据库时不创建文件；
- 多项参数错误时仍按格式、公司、姓名、邮箱、条数顺序报告首个错误，
  之后才检查 --after-id；
- 合法查询在父目录存在而数据库不存在时初始化空库并返回空结果；
  父目录不存在则报 db: parent directory does not exist；
- 查询不改变已有字段和编号。

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

AFTER_ID_ERROR_LINE = "after-id: must be a positive integer"
DB_ERROR_LINE = "db: parent directory does not exist"

# 上限 9223372036854775807（2**63 - 1）合法，超过上限一即被拒绝
MAX_AFTER_ID_TEXT = "9223372036854775807"
OVER_MAX_AFTER_ID_TEXT = "9223372036854775808"

# 空串、纯空白、0、负数、小数、非 ASCII 数字及超出上限的数值
INVALID_AFTER_IDS = [
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
    "１",
    "١٢٣",
    OVER_MAX_AFTER_ID_TEXT,
    "99999999999999999999999999",
]

CSV_HEADER = "id,name,email,company"


class ListAfterIdTestCase(unittest.TestCase):
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

    def delete_contact(self, db_path, contact_id):
        return self.run_crm(db_path, "delete", "--id", str(contact_id))

    def list_contacts(self, db_path, fmt=None, company=None, name=None,
                      email=None, limit=None, after_id=None):
        """执行 list；after_id 为 None 时省略 --after-id，空串等值仍原样传入。"""
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
        if after_id is not None:
            cli_args.extend(["--after-id", after_id])
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
        全新库中编号依次为 1、2、3（仍以 add 返回值为准）。
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

        self.assertEqual([r["id"] for r in (lin_ning, zhou_lan, xu_he)], [1, 2, 3])
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

    def assert_after_id_rejected(self, result):
        """断言 after-id 被拒绝：退出码 2、无标准输出、标准错误恰为单行、无堆栈。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        stderr_text = result.stderr.decode("utf-8")
        self.assertEqual(stderr_text, AFTER_ID_ERROR_LINE + "\n")
        self.assertNotIn("Traceback", stderr_text)

    def assert_db_error(self, result):
        """断言父目录缺失错误：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr.decode("utf-8"), DB_ERROR_LINE + "\n"
        )

    def parse_csv(self, raw_text):
        """按 CSV 规则解析标准输出。"""
        return list(csv.reader(io.StringIO(raw_text)))

    def assert_records_intact(self, expected_records):
        """用不带任何条件的 list 核对记录内容、编号与顺序完整保留。"""
        records = self.list_records(self.db_path)
        self.assertEqual(records, expected_records)

    # ---- 省略 --after-id 保持原行为 ----

    def test_without_after_id_keeps_original_behavior(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        expected = [lin_ning, zhou_lan, xu_he]

        # 省略 --after-id：全部三条，按编号升序
        self.assert_list_success(self.db_path, expected)
        # 公司筛选与条数限制的既有行为不受影响
        self.assert_list_success(
            self.db_path, [lin_ning], company=COMPANY_XINGHE, limit="1"
        )
        self.assert_records_intact(expected)

    # ---- 与公司条件取交集，并在升序后应用 limit ----

    def test_company_limit_without_after_id_returns_lin_ning(self):
        lin_ning, _zhou_lan, xu_he = self.seed_contacts()

        # list --company 星河科技 --limit 1 只返回林宁
        records = self.assert_list_success(
            self.db_path, [lin_ning], company=COMPANY_XINGHE, limit="1"
        )
        self.assertEqual(records[0]["id"], lin_ning["id"])

        self.assert_records_intact([lin_ning, _zhou_lan, xu_he])

    def test_company_limit_after_id_one_returns_xu_he(self):
        lin_ning, _zhou_lan, xu_he = self.seed_contacts()

        # 同一命令增加 --after-id 1：排除林宁后只返回许禾
        records = self.assert_list_success(
            self.db_path, [xu_he],
            company=COMPANY_XINGHE, limit="1", after_id="1",
        )
        self.assertEqual(records[0]["id"], xu_he["id"])
        self.assertEqual(records[0]["company"], COMPANY_XINGHE)

        self.assert_records_intact([lin_ning, _zhou_lan, xu_he])

    def test_after_id_one_alone_returns_zhou_lan_then_xu_he(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()

        # 移除公司和条数条件，仅 --after-id 1：依次返回周岚和许禾
        records = self.assert_list_success(
            self.db_path, [zhou_lan, xu_he], after_id="1"
        )
        self.assertEqual(
            [r["id"] for r in records], [zhou_lan["id"], xu_he["id"]]
        )
        self.assertEqual(
            [r["name"] for r in records], ["周岚", "许禾"]
        )

        self.assert_records_intact([lin_ning, zhou_lan, xu_he])

    # ---- 严格大于、交集、排序与条数 ----

    def test_after_id_is_strict_greater_than(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        expected = [lin_ning, zhou_lan, xu_he]

        # 边界命中存在记录时该记录被排除
        self.assert_list_success(self.db_path, [zhou_lan, xu_he], after_id="1")
        self.assert_list_success(self.db_path, [xu_he], after_id="2")
        self.assert_list_success(self.db_path, [], after_id="3")
        # 编号严格大于上界时无记录
        self.assert_list_success(self.db_path, [], after_id="10")

        self.assert_records_intact(expected)

    def test_after_id_intersects_name_and_email_filters(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()

        # 姓名子串"许"与 id > 2 的交集仍为许禾；id > 3 则为空
        self.assert_list_success(
            self.db_path, [xu_he], name="许", after_id="2"
        )
        self.assert_list_success(self.db_path, [], name="许", after_id="3")

        # 邮箱精确匹配与 after-id 取交集
        self.assert_list_success(
            self.db_path, [xu_he], email=XU_EMAIL, after_id="1"
        )
        self.assert_list_success(
            self.db_path, [], email=LIN_EMAIL, after_id="1"
        )

        # 公司、姓名、邮箱、after-id 全部满足时才命中
        self.assert_list_success(
            self.db_path, [xu_he],
            company=COMPANY_XINGHE, name="许", email=XU_EMAIL, after_id="2",
        )
        self.assert_list_success(
            self.db_path, [],
            company=COMPANY_XINGHE, name="许", email=XU_EMAIL, after_id="3",
        )

        self.assert_records_intact([lin_ning, zhou_lan, xu_he])

    def test_limit_applies_after_after_id_in_ascending_order(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()

        # 先按 id > 1 过滤并升序得到 [周岚, 许禾]，再截 1 条为周岚
        self.assert_list_success(
            self.db_path, [zhou_lan], after_id="1", limit="1"
        )
        # 限制为 10 时不补齐
        records = self.assert_list_success(
            self.db_path, [zhou_lan, xu_he], after_id="1", limit="10"
        )
        self.assertEqual(len(records), 2)

        self.assert_records_intact([lin_ning, zhou_lan, xu_he])

    # ---- 边界编号无需存在，删除后仍可用 ----

    def test_after_id_boundary_need_not_exist(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        expected = [lin_ning, zhou_lan, xu_he]

        # 不存在的编号同样按严格大于处理（前导零不影响）
        self.assert_list_success(
            self.db_path, [zhou_lan, xu_he], after_id="0001"
        )
        # 2 与 3 之间没有记录：边界编号 2 存在与否，查询表现一致
        self.assert_list_success(self.db_path, [xu_he], after_id="2")

        self.assert_records_intact(expected)

    def test_deleted_contact_id_still_usable_as_boundary(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()

        # 删除中间的周岚（id 2）后，编号 1、2 仍可作为查询边界
        delete_result = self.delete_contact(self.db_path, zhou_lan["id"])
        self.assertEqual(delete_result.returncode, 0,
                         delete_result.stderr.decode("utf-8"))
        self.assertEqual(delete_result.stderr, b"")

        remaining = [lin_ning, xu_he]
        # id > 1：只剩许禾；删除的周岚不 reappear
        self.assert_list_success(self.db_path, [xu_he], after_id="1")
        # 以被删除的编号 2 为边界：仍只返回许禾
        self.assert_list_success(self.db_path, [xu_he], after_id="2")
        self.assert_list_success(self.db_path, [], after_id="3")

        # 其余记录字段与编号不变
        self.assert_records_intact(remaining)

    # ---- 输出格式 ----

    def test_csv_matches_json_records_and_order(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        expected = [zhou_lan, xu_he]

        csv_result = self.list_contacts(
            self.db_path, fmt="csv", company=COMPANY_XINGHE,
            limit="1", after_id="1",
        )
        json_result = self.list_contacts(
            self.db_path, fmt="json", company=COMPANY_XINGHE,
            limit="1", after_id="1",
        )
        self.assertEqual(csv_result.returncode, 0, csv_result.stderr.decode("utf-8"))
        self.assertEqual(json_result.returncode, 0, json_result.stderr.decode("utf-8"))
        self.assertEqual(csv_result.stderr, b"")
        self.assertEqual(json_result.stderr, b"")

        json_records = json.loads(json_result.stdout.decode("utf-8"))
        self.assertEqual(json_records, [xu_he])

        rows = self.parse_csv(csv_result.stdout.decode("utf-8"))
        self.assertEqual(rows[0], CSV_HEADER.split(","))
        data_rows = rows[1:]
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

        # 跨公司 after-id：CSV 与 JSON 记录、顺序完全一致
        csv_all = self.list_contacts(self.db_path, fmt="csv", after_id="1")
        json_all = self.list_contacts(self.db_path, fmt="json", after_id="1")
        self.assertEqual(csv_all.stderr, b"")
        all_records = json.loads(json_all.stdout.decode("utf-8"))
        self.assertEqual(all_records, expected)
        all_rows = self.parse_csv(csv_all.stdout.decode("utf-8"))
        self.assertEqual(
            [row[0] for row in all_rows[1:]],
            [str(r["id"]) for r in expected],
        )

        # 无匹配时 JSON 为 []，CSV 只有表头
        no_match_json = self.list_contacts(self.db_path, after_id="9")
        self.assertEqual(json.loads(no_match_json.stdout.decode("utf-8")), [])
        no_match_csv = self.list_contacts(
            self.db_path, fmt="csv", after_id="9"
        )
        self.assertEqual(
            no_match_csv.stdout.decode("utf-8"), CSV_HEADER + "\r\n"
        )

        self.assert_records_intact([lin_ning, zhou_lan, xu_he])

    # ---- 参数边界 ----

    def test_after_id_with_whitespace_and_leading_zeros(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        expected_tail = [zhou_lan, xu_he]

        # 带首尾空白和前导零的写法与 1 结果相同
        for raw in (" 001 ", "001", "01", " 1 ", "\t1\t", " 001", "001 "):
            with self.subTest(after_id=raw):
                self.assert_list_success(
                    self.db_path, expected_tail, after_id=raw
                )

        self.assert_records_intact([lin_ning, zhou_lan, xu_he])

    def test_after_id_max_int64_is_valid(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        expected = [lin_ning, zhou_lan, xu_he]

        # 上限合法：所有编号都不大于它，结果为空数组而非报错
        self.assert_list_success(self.db_path, [], after_id=MAX_AFTER_ID_TEXT)
        # 与公司条件取交集后同样为空
        self.assert_list_success(
            self.db_path, [],
            company=COMPANY_XINGHE, after_id=MAX_AFTER_ID_TEXT,
        )

        self.assert_records_intact(expected)

    def test_invalid_after_ids_are_rejected(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()

        # 其他参数保持有效（公司筛选与格式均合法），唯一问题是 after-id
        for raw in INVALID_AFTER_IDS:
            with self.subTest(after_id=raw):
                result = self.list_contacts(
                    self.db_path,
                    company=COMPANY_XINGHE,
                    fmt="json",
                    after_id=raw,
                )
                self.assert_after_id_rejected(result)

        # 不带其他筛选条件时同样被拒绝
        for raw in ("", "0", "-1", "1.5", "abc", "１２３", OVER_MAX_AFTER_ID_TEXT):
            with self.subTest(after_id=raw):
                result = self.list_contacts(self.db_path, after_id=raw)
                self.assert_after_id_rejected(result)

        self.assert_records_intact([lin_ning, zhou_lan, xu_he])

    # ---- 错误报告顺序：格式、公司、姓名、邮箱、条数，之后才是 after-id ----

    def test_error_order_reports_earlier_field_before_after_id(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        bad_after_id = "0"

        cases = [
            ({"fmt": "xml"}, "format: must be json or csv"),
            ({"company": "  "}, "company: must not be empty"),
            ({"name": "  "}, "name: must not be empty"),
            ({"email": "no-at"}, "email: invalid email address"),
            ({"limit": "0"}, "limit: must be a positive integer"),
        ]
        for kwargs, expected_line in cases:
            with self.subTest(kwargs=kwargs):
                kwargs = dict(kwargs, after_id=bad_after_id)
                result = self.list_contacts(self.db_path, **kwargs)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(
                    result.stderr.decode("utf-8"), expected_line + "\n"
                )

        # 前五项全部合法、仅 after-id 非法时才报 after-id
        result = self.list_contacts(
            self.db_path,
            company=COMPANY_XINGHE, name="许", email=XU_EMAIL,
            limit="1", after_id=bad_after_id,
        )
        self.assert_after_id_rejected(result)

        self.assert_records_intact([lin_ning, zhou_lan, xu_he])

    # ---- 不存在的数据库 ----

    def test_invalid_after_id_does_not_create_missing_database(self):
        fresh_db = self.tmpdir / "fresh-after.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 无效值在连接数据库前失败：文件及任何 SQLite 伴随文件都不应出现
        for raw in ("", "0", "-1", "abc", OVER_MAX_AFTER_ID_TEXT):
            with self.subTest(after_id=raw):
                result = self.list_contacts(fresh_db, after_id=raw)
                self.assert_after_id_rejected(result)
                self.assertFalse(fresh_db.exists())
                self.assertEqual(list(self.tmpdir.glob(fresh_db.name + "*")), [])

        # 合法 after-id 查询同样的新路径：创建空库并返回空结果
        result = self.list_contacts(fresh_db, after_id="1")
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout.decode("utf-8")), [])
        self.assertTrue(fresh_db.exists())

        # 不带 after-id 再次查询仍为空数组
        again = self.list_contacts(fresh_db)
        self.assertEqual(again.returncode, 0, again.stderr.decode("utf-8"))
        self.assertEqual(again.stderr, b"")
        self.assertEqual(json.loads(again.stdout.decode("utf-8")), [])

    def test_valid_query_with_missing_parent_directory_is_rejected(self):
        missing_parent_db = self.tmpdir / "no-such-dir" / "contacts.sqlite3"

        # after-id 合法但父目录不存在：报 db 错误且不创建任何文件
        result = self.list_contacts(missing_parent_db, after_id="1")
        self.assert_db_error(result)
        self.assertFalse((self.tmpdir / "no-such-dir").exists())

        # 无任何筛选条件的既有行为一致，作为对照
        control = self.list_contacts(missing_parent_db)
        self.assert_db_error(control)

    # ---- 查询对已有数据的影响 ----

    def test_after_id_queries_leave_records_unchanged(self):
        lin_ning, zhou_lan, xu_he = self.seed_contacts()
        expected = [lin_ning, zhou_lan, xu_he]

        successful = [
            {"after_id": "1"},
            {"after_id": "2"},
            {"after_id": "3"},
            {"after_id": "10"},
            {"company": COMPANY_XINGHE, "limit": "1", "after_id": "1"},
            {"name": "许", "after_id": "1"},
            {"email": XU_EMAIL, "after_id": "1"},
            {"fmt": "csv", "after_id": "1"},
            {"after_id": MAX_AFTER_ID_TEXT},
            {"after_id": " 001 "},
        ]
        for kwargs in successful:
            with self.subTest(kwargs=kwargs):
                result = self.list_contacts(self.db_path, **kwargs)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
                self.assertEqual(result.stderr, b"")

        # 成功查询之后：记录完整保留
        self.assert_records_intact(expected)

        # 失败查询之后：记录内容、编号与顺序仍完整保留
        for raw in INVALID_AFTER_IDS:
            with self.subTest(after_id=raw):
                result = self.list_contacts(self.db_path, after_id=raw)
                self.assert_after_id_rejected(result)

        self.assert_records_intact(expected)


if __name__ == "__main__":
    unittest.main()
