"""crm.py 命令行行为的回归测试。

通过子进程调用项目根目录下的 crm.py，覆盖：
- 正常新增与按公司精确筛选（含首尾空格清理、邮箱大小写保留、id 升序）
- 无效姓名 / 公司 / 邮箱的拒绝（退出码、输出、且不写入任何记录）
- 数据库父目录不存在时的拒绝（不创建父目录）

每个用例使用独立的临时目录，不依赖个人数据库或网络，结束后自动清理。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CRM = PROJECT_ROOT / "crm.py"


def run_crm(*args):
    """以独立进程运行 crm.py，返回 CompletedProcess。"""
    return subprocess.run(
        [sys.executable, str(CRM), *args],
        capture_output=True,
        text=True,
    )


class CrmTestCase(unittest.TestCase):
    """每个用例一个独立临时目录，测试结束自动清理。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "contacts.db"

    # ---------- 辅助方法 ----------

    def add_contact(self, name, email, company, db=None):
        return run_crm(
            "--db", str(db or self.db),
            "add", "--name", name, "--email", email, "--company", company,
        )

    def list_company(self, company, db=None):
        return run_crm(
            "--db", str(db or self.db),
            "list", "--company", company,
        )

    def assert_add_ok(self, result, name, email, company):
        """断言新增成功，返回解析出的联系人字典。"""
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        self.assertEqual(result.stderr, "")
        record = json.loads(result.stdout)
        self.assertIsInstance(record, dict)
        self.assertIsInstance(record["id"], int)
        self.assertEqual(
            {"id": record["id"], "name": name, "email": email, "company": company},
            record,
        )
        return record

    def assert_rejected(self, result, expected_stderr):
        """断言输入被拒绝：退出码 2、标准输出为空、标准错误为指定消息。"""
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(), expected_stderr)

    def assert_list_matches(self, company, expected_records, db=None):
        """断言 list 输出与期望记录一致（dict 比较不依赖键序，列表保持 id 升序）。"""
        result = self.list_company(company, db=db)
        self.assertEqual(result.returncode, 0, msg=f"stderr: {result.stderr}")
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout), expected_records)

    # ---------- 正常样例 ----------

    def test_add_and_list_roundtrip(self):
        lin = self.assert_add_ok(
            self.add_contact("  林宁  ", "  Lin.Ning@example.test  ", "  星河科技  "),
            name="林宁", email="Lin.Ning@example.test", company="星河科技",
        )
        xu = self.assert_add_ok(
            self.add_contact("许禾", "xuhe@example.test", "星河科技"),
            name="许禾", email="xuhe@example.test", company="星河科技",
        )
        zhou = self.assert_add_ok(
            self.add_contact("周岚", "zhoulan@example.test", "远帆咨询"),
            name="周岚", email="zhoulan@example.test", company="远帆咨询",
        )

        # id 为自增整数且互不相同
        ids = [lin["id"], xu["id"], zhou["id"]]
        self.assertEqual(len(set(ids)), 3)

        # 另起进程查询：星河科技只有林宁、许禾，按 id 升序
        self.assertListEqual(sorted([lin["id"], xu["id"]]), [lin["id"], xu["id"]])
        self.assert_list_matches("星河科技", [lin, xu])
        # 远帆咨询只有周岚
        self.assert_list_matches("远帆咨询", [zhou])

    # ---------- 异常样例：字段校验 ----------

    def seed_contacts(self):
        """在数据库中写入正常样例数据，返回新增结果列表。"""
        return [
            self.assert_add_ok(
                self.add_contact("  林宁  ", "  Lin.Ning@example.test  ", "  星河科技  "),
                name="林宁", email="Lin.Ning@example.test", company="星河科技",
            ),
            self.assert_add_ok(
                self.add_contact("许禾", "xuhe@example.test", "星河科技"),
                name="许禾", email="xuhe@example.test", company="星河科技",
            ),
            self.assert_add_ok(
                self.add_contact("周岚", "zhoulan@example.test", "远帆咨询"),
                name="周岚", email="zhoulan@example.test", company="远帆咨询",
            ),
        ]

    def assert_companies_unchanged(self, lin, xu, zhou):
        """拒绝无效输入后，两家公司的记录内容与数量保持不变。"""
        self.assert_list_matches("星河科技", [lin, xu])
        self.assert_list_matches("远帆咨询", [zhou])

    def test_blank_name_rejected(self):
        lin, xu, zhou = self.seed_contacts()
        self.assert_rejected(
            self.add_contact("   ", "valid@example.test", "星河科技"),
            "name: must not be empty",
        )
        self.assert_companies_unchanged(lin, xu, zhou)

    def test_blank_company_rejected(self):
        lin, xu, zhou = self.seed_contacts()
        self.assert_rejected(
            self.add_contact("有效姓名", "valid@example.test", " \t "),
            "company: must not be empty",
        )
        self.assert_companies_unchanged(lin, xu, zhou)

    def test_invalid_emails_rejected(self):
        lin, xu, zhou = self.seed_contacts()
        invalid_emails = [
            "no-at-sign.example.test",   # 缺少 @
            "two@@example.test",         # 包含两个 @
            "user@nodot",                # 域名没有点
            "user@example..test",        # 域名含空段
            "user name@example.test",    # 邮箱内部含空白
        ]
        for email in invalid_emails:
            with self.subTest(email=email):
                self.assert_rejected(
                    self.add_contact("有效姓名", email, "星河科技"),
                    "email: invalid email address",
                )
        self.assert_companies_unchanged(lin, xu, zhou)

    # ---------- 异常样例：不存在的数据库文件 ----------

    def test_rejection_does_not_create_db_file(self):
        db = self.tmp / "fresh.db"
        cases = [
            (("   ", "valid@example.test", "星河科技"), "name: must not be empty"),
            (("有效姓名", "valid@example.test", "  "), "company: must not be empty"),
            (("有效姓名", "bad-email", "星河科技"), "email: invalid email address"),
        ]
        for (name, email, company), message in cases:
            with self.subTest(message=message):
                self.assert_rejected(self.add_contact(name, email, company, db=db), message)
                self.assertFalse(db.exists(), "拒绝无效输入后不应创建数据库文件")

    # ---------- 异常样例：父目录不存在 ----------

    def test_missing_parent_directory_rejected(self):
        missing_dir = self.tmp / "no" / "such" / "dir"
        db = missing_dir / "contacts.db"
        result = self.add_contact("林宁", "Lin.Ning@example.test", "星河科技", db=db)
        self.assert_rejected(result, "db: parent directory does not exist")
        self.assertFalse(missing_dir.exists(), "不应创建缺失的父目录")
        self.assertFalse(db.exists())


if __name__ == "__main__":
    unittest.main()
