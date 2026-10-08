# 本地客户关系管理台

面向本地单机使用的联系人管理命令行工具，仅依赖 Python 3 标准库，数据持久化在本地 SQLite 数据库文件中。

本指南只覆盖两件最常用的操作：**新增联系人**与**按公司筛选查询**。工具还支持查看、更新、删除、汇总、备注等其他子命令，本指南不展开。

## 运行前提

- 安装 Python 3（无需任何第三方包）。
- 在 `crm.py` 所在目录中执行本文所有命令。
- `--db` 是**必填参数**，且必须写在子命令（如 `add`、`list`）**之前**。
- `--db` 指向的数据库文件，其父目录必须已经存在。文件本身不存在时，一条有效请求会自动初始化该数据库；文件已存在时则复用其中的数据，因此联系人可以在后续独立的命令调用中查到。

## 新增联系人

子命令 `add` 需要 `--name`、`--email`、`--company` 三个参数。新增成功时输出**单个联系人 JSON 对象**，包含 `id`、`name`、`email`、`company` 四个字段，退出码为 0，标准错误为空。

以下样例统一使用一个**全新的** `demo.sqlite3`。依次新增三位联系人：

```bash
python3 crm.py --db demo.sqlite3 add --name 林宁 --email lin@example.test --company 星河科技
```

预期结果：

```json
{"id": 1, "name": "林宁", "email": "lin@example.test", "company": "星河科技"}
```

```bash
python3 crm.py --db demo.sqlite3 add --name 周岚 --email zhou@example.test --company 远帆咨询
```

预期结果：

```json
{"id": 2, "name": "周岚", "email": "zhou@example.test", "company": "远帆咨询"}
```

```bash
python3 crm.py --db demo.sqlite3 add --name 许禾 --email xu@example.test --company 星河科技
```

预期结果：

```json
{"id": 3, "name": "许禾", "email": "xu@example.test", "company": "星河科技"}
```

在全新数据库中，三条记录的编号依次为 1、2、3。若使用已有数据库，编号以每次新增输出中的实际 `id` 为准。

姓名、邮箱、公司只清理首尾空白，内部字符与大小写原样保留。

## 按公司筛选查询

子命令 `list` 输出**JSON 数组**，每条记录同样包含 `id`、`name`、`email`、`company`，按编号升序排列，成功时退出码为 0，标准错误为空。

`--company` 可选：传入时先去除首尾空白，再按公司名**精确匹配且区分大小写**；省略时查询全部公司，公司参数并非必填。

查询星河科技（预期返回林宁和许禾）：

```bash
python3 crm.py --db demo.sqlite3 list --company 星河科技
```

预期结果：

```json
[{"id": 1, "name": "林宁", "email": "lin@example.test", "company": "星河科技"}, {"id": 3, "name": "许禾", "email": "xu@example.test", "company": "星河科技"}]
```

查询远帆咨询（预期只返回周岚）：

```bash
python3 crm.py --db demo.sqlite3 list --company 远帆咨询
```

预期结果：

```json
[{"id": 2, "name": "周岚", "email": "zhou@example.test", "company": "远帆咨询"}]
```

没有匹配的公司时返回空数组 `[]`，退出码仍为 0。省略 `--company` 则返回全部三家公司的三位联系人。

由于数据保存在 `demo.sqlite3` 中，以上查询可以在新增之后的任何一次独立调用中重复执行并得到相同结果。

## 失败示例

输入不合法时，命令以退出码 2 结束，标准输出为空，错误信息写入标准错误。字段校验失败不会创建新的数据库文件，也不会改变已有联系人。

姓名仅含空白：

```bash
python3 crm.py --db demo.sqlite3 add --name "   " --email lin@example.test --company 星河科技
```

预期标准错误：

```
name: must not be empty
```

邮箱缺少 `@`：

```bash
python3 crm.py --db demo.sqlite3 add --name 林宁 --email lin.example.test --company 星河科技
```

预期标准错误：

```
email: invalid email address
```

公司仅含空白：

```bash
python3 crm.py --db demo.sqlite3 add --name 林宁 --email lin@example.test --company "  "
```

预期标准错误：

```
company: must not be empty
```

业务输入有效但数据库父目录不存在：

```bash
python3 crm.py --db no_such_dir/demo.sqlite3 add --name 林宁 --email lin@example.test --company 星河科技
```

预期标准错误：

```
db: parent directory does not exist
```

> 以上所有命令输出均为与当前命令行为核对后的预期结果说明，并非逐次执行的记录存档。
