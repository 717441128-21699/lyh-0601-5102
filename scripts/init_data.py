import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, engine, Base
from app.models import Customer
from app.schemas import CustomerCreate
from app.services import customer_service

SAMPLE_CUSTOMERS = [
    {
        "customer_code": "CUST001",
        "customer_name": "北京华信科技有限公司",
        "customer_level": "VIP",
        "contact_person": "张三",
        "contact_phone": "13800138001",
        "contact_email": "zhangsan@huaxin.com",
        "address": "北京市朝阳区建国路88号",
        "industry": "信息技术",
        "department": "销售一部",
        "order_manager": "李经理"
    },
    {
        "customer_code": "CUST002",
        "customer_name": "上海宏远贸易有限公司",
        "customer_level": "NORMAL",
        "contact_person": "李四",
        "contact_phone": "13900139002",
        "contact_email": "lisi@hongyuan.com",
        "address": "上海市浦东新区陆家嘴环路1000号",
        "industry": "贸易",
        "department": "销售二部",
        "order_manager": "王主管"
    },
    {
        "customer_code": "CUST003",
        "customer_name": "深圳创新电子有限公司",
        "customer_level": "NORMAL",
        "contact_person": "王五",
        "contact_phone": "13700137003",
        "contact_email": "wangwu@chuangxin.com",
        "address": "深圳市南山区科技园南路10号",
        "industry": "电子制造",
        "department": "销售一部",
        "order_manager": "李经理"
    },
    {
        "customer_code": "CUST004",
        "customer_name": "广州盛达物流有限公司",
        "customer_level": "VIP",
        "contact_person": "赵六",
        "contact_phone": "13600136004",
        "contact_email": "zhaoliu@shengda.com",
        "address": "广州市天河区体育西路200号",
        "industry": "物流",
        "department": "销售三部",
        "order_manager": "陈总监"
    },
    {
        "customer_code": "CUST005",
        "customer_name": "杭州瑞联网络科技有限公司",
        "customer_level": "NORMAL",
        "contact_person": "孙七",
        "contact_phone": "13500135005",
        "contact_email": "sunqi@ruilian.com",
        "address": "杭州市西湖区文三路90号",
        "industry": "互联网",
        "department": "销售二部",
        "order_manager": "王主管"
    }
]


def init_database():
    Base.metadata.create_all(bind=engine)
    print("数据库表创建完成")

    db = SessionLocal()
    try:
        existing_count = db.query(Customer).count()
        if existing_count > 0:
            print(f"数据库已存在 {existing_count} 条客户数据，跳过初始化")
            return

        for cust_data in SAMPLE_CUSTOMERS:
            customer_create = CustomerCreate(**cust_data)
            customer_service.create_customer(db, customer_create, "SYSTEM_INIT")
            print(f"已创建客户: {cust_data['customer_name']}")

        print("示例数据初始化完成")
    finally:
        db.close()


if __name__ == "__main__":
    init_database()
