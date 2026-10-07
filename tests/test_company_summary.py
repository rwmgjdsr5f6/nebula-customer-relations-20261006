"""crm.py company-summary 子命令（按公司汇总联系人数量）的回归测试。

仅验收 company-summary 的既有命令行行为：

- 成功时退出码 0、标准错误为空，标准输出整体只有一个 JSON 数组；每项只含
  company（字符串）与 contact_count（整数），按完整公司名精确归组、区分大小写，
  按公司名 Unicode 码点升序排列，只包含至少有一条联系人记录的公司；
- 同名或同邮箱的不同联系人记录分别计数，不被去重；公司人数降为 0 后该公司
  整组消失，不保留零人数项；
- 每次汇总都启动新的 crm.py 子进程，重复查询同一数据库结果一致，且汇总
  不修改任何联系人记录（用已有 list 命令对照查询前后的完整记录）；
- 已有数据库为空时返回 []；父目录存在而数据库文件不存在时，汇总成功创建
  可复用的空库并返回 []，再次查询仍为空；
- 父目录不存在时退出码 2、标准输出为空，标准错误恰为
  db: parent directory does not exist 加行尾换行，目录和数据库都不被创建。

add、list、delete 在本模块仅用于准备样例和对照数据。仅使用 Python 3 标准库
unittest，通过子进程执行 crm.py，所有样例数据都放在各自独立的临时数据库中，
不读取已有客户库，不依赖网络或第三方包，测试结束后自动清理，重复执行结果一致。
在项目根目录运行：python -m unittest discover -s tests
"""

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

DB_ERROR_LINE = "db: parent directory does not exist"


class CompanySummaryTestCase(unittest.TestCase):
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

    def company_summary(self, db_path):
        return self.run_crm(db_path, "company-summary")

    def list_all(self, db_path):
        """省略 --company 的跨公司全量 list，用于对照完整联系人记录。"""
        return self.run_crm(db_path, "list")

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

    def assert_delete_success(self, result, expected):
        """断言删除成功并返回解析后的被删除联系人字典。"""
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        record = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(record.keys()), {"id", "name", "email", "company"})
        self.assertEqual(record, expected)
        return record

    def assert_list_all_records(self, db_path, expected_records):
        """断言全量 list 成功并返回解析后的记录（按 id 升序，含顺序完全一致）。"""
        result = self.list_all(db_path)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(records, expected_records)
        return records

    def parse_single_json_array(self, raw_stdout):
        """把标准输出解析为单个 JSON 数组，拒绝除该数组外的任何多余输出。

        不依赖 JSON 的缩进或对象键排列：去掉首尾空白后，用 raw_decode
        恰好消费完全部文本，且值必须是数组。
        """
        text = raw_stdout.decode("utf-8")
        body = text.strip()
        records, end = json.JSONDecoder().raw_decode(body)
        self.assertEqual(end, len(body))
        self.assertIsInstance(records, list)
        return records

    def assert_summary_records(self, db_path, expected_records):
        """断言 company-summary 成功并返回（含顺序）与期望完全一致的数组。

        成功时退出码 0、标准错误为空；标准输出整体只有一个 JSON 数组；
        每项只含 company（字符串）与 contact_count（整数）。
        """
        result = self.company_summary(db_path)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        records = self.parse_single_json_array(result.stdout)
        for item in records:
            self.assertIsInstance(item, dict)
            self.assertEqual(set(item.keys()), {"company", "contact_count"})
            self.assertIsInstance(item["company"], str)
            self.assertIsInstance(item["contact_count"], int)
        self.assertEqual(records, expected_records)
        return records

    def assert_summary_rejected(self, result, expected_stderr_line):
        """断言 company-summary 被拒绝：退出码 2、无标准输出、标准错误恰为单行。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        stderr_text = result.stderr.decode("utf-8")
        self.assertEqual(stderr_text, expected_stderr_line + "\n")
        self.assertNotIn("Traceback", stderr_text)

    def assert_summary_and_data_unchanged(
        self, db_path, expected_summary, expected_contacts
    ):
        """汇总并核对结果，同时用全量 list 对照汇总前后数据，再重复一轮。

        每次 company-summary、list 都是新启动的子进程：
        - 汇总前全量 list 与期望联系人记录一致；
        - company-summary 结果（内容与顺序）与期望汇总一致；
        - 汇总后全量 list 与汇总前完全相同，汇总不修改数据；
        - 重新启动命令再次汇总结果相同，随后全量 list 仍然不变。
        """
        before = self.assert_list_all_records(db_path, expected_contacts)

        records = self.assert_summary_records(db_path, expected_summary)

        after = self.assert_list_all_records(db_path, expected_contacts)
        self.assertEqual(before, after)

        # 再次查询同一数据库应得到相同结果
        self.assert_summary_records(db_path, expected_summary)
        self.assert_list_all_records(db_path, expected_contacts)
        return records

    def seed_main_sample_contacts(self):
        """主样例：独立新数据库中先新增远帆咨询的周岚，再新增星河科技的两人。

        新增顺序刻意与汇总顺序相反，返回三条新增结果（编号取自新增输出）。
        """
        zhou = self.assert_add_success(
            self.add_contact(
                self.db_path, "周岚", "zhou@example.test", COMPANY_YUANFAN
            ),
            {
                "name": "周岚",
                "email": "zhou@example.test",
                "company": COMPANY_YUANFAN,
            },
        )
        lin = self.assert_add_success(
            self.add_contact(
                self.db_path, "林宁", "lin@example.test", COMPANY_XINGHE
            ),
            {
                "name": "林宁",
                "email": "lin@example.test",
                "company": COMPANY_XINGHE,
            },
        )
        xu = self.assert_add_success(
            self.add_contact(
                self.db_path, "许禾", "xu@example.test", COMPANY_XINGHE
            ),
            {
                "name": "许禾",
                "email": "xu@example.test",
                "company": COMPANY_XINGHE,
            },
        )
        self.assertLess(zhou["id"], lin["id"])
        self.assertLess(lin["id"], xu["id"])
        return zhou, lin, xu

    # ---- 主样例：精确归组、码点排序、不去重、无零人数项 ----

    def test_summary_groups_counts_sorts_and_tracks_changes(self):
        zhou, lin, xu = self.seed_main_sample_contacts()

        # 汇总先返回星河科技 2 人，再返回远帆咨询 1 人：
        # 星（U+661F）码点小于远（U+8FDC），与新增顺序相反
        self.assert_summary_and_data_unchanged(
            self.db_path,
            [
                {"company": COMPANY_XINGHE, "contact_count": 2},
                {"company": COMPANY_YUANFAN, "contact_count": 1},
            ],
            [zhou, lin, xu],
        )

        # 再新增一条与林宁同姓名、同邮箱、同公司的记录：分别计数，不被去重
        lin_duplicate = self.assert_add_success(
            self.add_contact(
                self.db_path, "林宁", "lin@example.test", COMPANY_XINGHE
            ),
            {
                "name": "林宁",
                "email": "lin@example.test",
                "company": COMPANY_XINGHE,
            },
        )
        self.assertNotEqual(lin_duplicate["id"], lin["id"])

        self.assert_summary_and_data_unchanged(
            self.db_path,
            [
                {"company": COMPANY_XINGHE, "contact_count": 3},
                {"company": COMPANY_YUANFAN, "contact_count": 1},
            ],
            [zhou, lin, xu, lin_duplicate],
        )

        # 删除周岚：编号取自新增结果；远帆咨询降为 0 人后整组消失
        deleted_zhou = self.assert_delete_success(
            self.delete_contact(self.db_path, zhou["id"]), zhou
        )
        self.assertEqual(deleted_zhou["id"], zhou["id"])

        self.assert_summary_and_data_unchanged(
            self.db_path,
            [{"company": COMPANY_XINGHE, "contact_count": 3}],
            [lin, xu, lin_duplicate],
        )

    def test_summary_output_is_a_single_json_array(self):
        self.seed_main_sample_contacts()

        result = self.company_summary(self.db_path)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")

        # 标准输出去掉首尾空白后恰好是一个 JSON 数组，数组之外无多余输出
        records = self.parse_single_json_array(result.stdout)
        self.assertEqual(
            records,
            [
                {"company": COMPANY_XINGHE, "contact_count": 2},
                {"company": COMPANY_YUANFAN, "contact_count": 1},
            ],
        )

    # ---- 区分大小写的小样例 ----

    def test_summary_groups_acme_and_lowercase_acme_separately(self):
        # Acme 与 acme 各一位联系人：精确归组、区分大小写，Acme 码点在前
        alice = self.assert_add_success(
            self.add_contact(self.db_path, "Alice", "alice@example.test", "Acme"),
            {"name": "Alice", "email": "alice@example.test", "company": "Acme"},
        )
        bob = self.assert_add_success(
            self.add_contact(self.db_path, "Bob", "bob@example.test", "acme"),
            {"name": "Bob", "email": "bob@example.test", "company": "acme"},
        )
        self.assertLess(alice["id"], bob["id"])

        self.assert_summary_and_data_unchanged(
            self.db_path,
            [
                {"company": "Acme", "contact_count": 1},
                {"company": "acme", "contact_count": 1},
            ],
            [alice, bob],
        )

    # ---- 空数据库 ----

    def test_summary_empty_existing_database_returns_empty_array(self):
        # 先新增再删除，得到一个已存在但没有任何联系人的数据库
        zhou = self.assert_add_success(
            self.add_contact(
                self.db_path, "周岚", "zhou@example.test", COMPANY_YUANFAN
            ),
            {
                "name": "周岚",
                "email": "zhou@example.test",
                "company": COMPANY_YUANFAN,
            },
        )
        self.assert_delete_success(self.delete_contact(self.db_path, zhou["id"]), zhou)
        self.assertTrue(self.db_path.exists())

        # 空库汇总返回 []，重复查询仍为 []，全量 list 同样为空
        self.assert_summary_and_data_unchanged(self.db_path, [], [])

    def test_summary_creates_missing_database_and_returns_empty_array(self):
        fresh_db = self.tmpdir / "summary-fresh.sqlite3"
        self.assertFalse(fresh_db.exists())

        # 父目录存在、数据库文件不存在：成功创建可复用的空库并返回 []
        result = self.company_summary(fresh_db)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(self.parse_single_json_array(result.stdout), [])
        self.assertTrue(fresh_db.exists())

        # 再次启动命令查询同一数据库仍返回空数组
        again = self.company_summary(fresh_db)
        self.assertEqual(again.returncode, 0, again.stderr.decode("utf-8"))
        self.assertEqual(again.stderr, b"")
        self.assertEqual(self.parse_single_json_array(again.stdout), [])

        # 创建出的空库可被已有 list 命令复用，且仍没有任何联系人
        self.assert_list_all_records(fresh_db, [])

    # ---- 父目录不存在 ----

    def test_summary_missing_parent_directory_is_rejected_without_being_created(self):
        missing_parent = self.tmpdir / "no-such-parent"
        fresh_db = missing_parent / "contacts.sqlite3"
        self.assertFalse(missing_parent.exists())

        result = self.company_summary(fresh_db)
        self.assert_summary_rejected(result, DB_ERROR_LINE)
        # 目录和数据库都不被创建
        self.assertFalse(missing_parent.exists())
        self.assertFalse(fresh_db.exists())


if __name__ == "__main__":
    unittest.main()
