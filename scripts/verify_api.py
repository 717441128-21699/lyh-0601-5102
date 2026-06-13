import requests
import json

base_url = "http://localhost:8000"

print("=" * 60)
print("API功能验证")
print("=" * 60)

print("\n【1】首页统计")
r = requests.get(f"{base_url}/api/dashboard")
print(f"  状态码: {r.status_code}")
data = r.json()
print(f"  今日提交: {data['today_submitted']}")
print(f"  今日通过: {data['today_approved']}")
print(f"  待办总数: {data['todo_stats']['total_todo']}")
print(f"  超时待办: {data['todo_stats']['overdue_count']}")
print(f"  高优先级待办: {data['todo_stats']['high_priority_count']}")
assert r.status_code == 200

print("\n【2】审批链列表")
r = requests.get(f"{base_url}/api/approval/chains")
print(f"  状态码: {r.status_code}")
chains_data = r.json()
print(f"  审批链数量: {chains_data['total']}")
assert r.status_code == 200
assert chains_data['total'] >= 5

print("\n【3】审批规则列表")
r = requests.get(f"{base_url}/api/approval/rules")
print(f"  状态码: {r.status_code}")
rules_data = r.json()
print(f"  规则数量: {rules_data['total']}")
assert r.status_code == 200
assert rules_data['total'] >= 5

print("\n【4】待办统计")
r = requests.get(f"{base_url}/api/approval/todo/stats", params={"role": "REGIONAL_MANAGER"})
print(f"  状态码: {r.status_code}")
stats = r.json()
print(f"  总待办: {stats['total_todo']}")
print(f"  今日待办: {stats['today_todo']}")
print(f"  超时数: {stats['overdue_count']}")
assert r.status_code == 200

print("\n【5】7天趋势")
r = requests.get(f"{base_url}/api/reports/trend/7day")
print(f"  状态码: {r.status_code}")
trend = r.json()["trend"]
print(f"  趋势数据天数: {len(trend)}")
assert r.status_code == 200
assert len(trend) == 7

print("\n【6】30天趋势")
r = requests.get(f"{base_url}/api/reports/trend/30day")
print(f"  状态码: {r.status_code}")
trend30 = r.json()["trend"]
print(f"  趋势数据天数: {len(trend30)}")
assert r.status_code == 200
assert len(trend30) == 30

print("\n【7】变更申请列表（快捷筛选7天）")
r = requests.get(f"{base_url}/api/change-requests", params={"quick_range": "7d"})
print(f"  状态码: {r.status_code}")
data = r.json()
print(f"  总条数: {data['total']}")
assert r.status_code == 200

print("\n【8】变更申请列表（快捷筛选今天）")
r = requests.get(f"{base_url}/api/change-requests", params={"quick_range": "today"})
print(f"  状态码: {r.status_code}")
data = r.json()
print(f"  今天条数: {data['total']}")
assert r.status_code == 200

print("\n【9】客户风控状态")
r = requests.get(f"{base_url}/api/risk/customers/1/status")
print(f"  状态码: {r.status_code}")
if r.status_code == 200:
    status = r.json()
    print(f"  风控状态: {status['status']}")
    print(f"  30天变更数: {status['change_count_30d']}")
    print(f"  是否冻结: {status['is_frozen']}")

print("\n【10】导出变更申请（快捷筛选今天）")
r = requests.get(f"{base_url}/api/export/change-requests", params={"quick_range": "today"})
print(f"  状态码: {r.status_code}")
print(f"  内容类型: {r.headers.get('content-type')}")
assert r.status_code == 200
assert "spreadsheet" in r.headers.get('content-type', '')

print("\n【11】审批记录查询")
r = requests.get(f"{base_url}/api/approval/records/2")
print(f"  状态码: {r.status_code}")
if r.status_code == 200:
    records = r.json()
    print(f"  审批记录数: {len(records)}")

print("\n【12】日报详情（结构化统计）")
from datetime import date
today = date.today().isoformat()
r = requests.get(f"{base_url}/api/reports/daily/{today}/detail")
print(f"  状态码: {r.status_code}")
if r.status_code == 200:
    detail = r.json()
    print(f"  日期: {detail['report_date']}")
    print(f"  总申请数: {detail['total_requests']}")
    print(f"  部门统计数: {len(detail.get('department_stats', {}))}")

print("\n" + "=" * 60)
print("所有API验证通过！")
print("=" * 60)
