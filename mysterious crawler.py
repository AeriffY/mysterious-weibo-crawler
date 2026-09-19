from pathlib import Path
import json
import csv
import time

from playwright.sync_api import sync_playwright

#Playwright 持久化 Chrome 用户目录
#需要先登录一次微博
USER_DATA_DIR = Path("./weibo_browser")

WEIBO_ID = "5344586424910558"

PROGRESS_FILE = Path("./weibo_repost_progress.json")

CSV_FILE = Path("./weibo_common_following.csv")


#收集转发用户
SCROLL_DISTANCE = 1500

SCROLL_WAIT = 2500

MAX_IDLE_ROUNDS = 10


#检查共同关注
COMMON_FOLLOW_WAIT = 2000

#单个UID最多尝试次数
MAX_RETRIES = 3

RETRY_WAIT = 3000


def save_progress(users, checked_users):
    data = {
        "weibo_id": WEIBO_ID,
        "users": users,
        "checked_users": checked_users
    }

    temp_file = PROGRESS_FILE.with_suffix(".tmp")

    with temp_file.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    temp_file.replace(PROGRESS_FILE)


def load_progress():

    if not PROGRESS_FILE.exists():

        print(
            "没有找到已有进度文件，"
        )

        return {}, {}

    try:
        with PROGRESS_FILE.open(
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        # 检查是不是同一条微博
        saved_weibo_id = str(
            data.get(
                "weibo_id",
                ""
            )
        )

        if saved_weibo_id != WEIBO_ID:

            print(
                "发现进度文件，"
                "但微博 ID 不一致。"
            )

            print(
                "忽略旧进度，从头开始。"
            )

            return {}, {}

        users = data.get(
            "users",
            {}
        )

        checked_users = data.get(
            "checked_users",
            {}
        )

        print()
        print("=" * 70)
        print("读取已有进度")
        print("=" * 70)

        print(
            f"已经收集的转发用户："
            f"{len(users)}"
        )

        print(
            f"已经检查的用户："
            f"{len(checked_users)}"
        )

        return users, checked_users

    except Exception as e:
        print()
        print(
            "读取进度文件失败："
        )
        print(e)
        print(
            "本次从空状态开始。"
        )

        return {}, {}


def collect_repost_users(
    page,
    users,
    checked_users
):

    response_count = 0

    def handle_response(response):

        nonlocal response_count

        if "repostTimeline" not in response.url:
            return

        try:
            data = response.json()

        except Exception:
            return

        response_count += 1

        reposts = (
            data
            .get("data", {})
            .get("data", [])
        )

        new_users = 0

        for item in reposts:
            user = item.get(
                "user",
                {}
            )

            uid = user.get("id")
            name = user.get(
                "screen_name"
            )

            if uid is None:
                continue

            uid = str(uid)

            if uid not in users:
                users[uid] = name
                new_users += 1

        if new_users > 0:

            print(
                f"发现 {new_users} 个新用户，"
                f"累计 {len(users)} 个"
            )

            save_progress(
                users,
                checked_users
            )

    page.on(
        "response",
        handle_response
    )

    url = (
        f"https://m.weibo.cn/detail/"
        f"{WEIBO_ID}#repost"
    )

    print()
    print("=" * 70)
    print("收集转发用户")
    print("=" * 70)

    print(
        f"打开：{url}"
    )

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(
        5000
    )

    idle_rounds = 0
    round_number = 0

    while True:
        round_number += 1

        print()
        print(
            f"========== "
            f"第 {round_number} 轮滚动 "
            f"=========="
        )

        before_response_count = (
            response_count
        )

        before_user_count = (
            len(users)
        )

        page.mouse.wheel(
            0,
            SCROLL_DISTANCE
        )

        page.wait_for_timeout(
            SCROLL_WAIT
        )

        new_responses = (
            response_count
            - before_response_count
        )

        new_users = (
            len(users)
            - before_user_count
        )

        print(
            f"本轮新增请求："
            f"{new_responses}"
        )

        print(
            f"本轮新增用户："
            f"{new_users}"
        )

        print(
            f"累计请求："
            f"{response_count}"
        )

        print(
            f"累计用户："
            f"{len(users)}"
        )

        if (
            new_responses == 0
            and new_users == 0
        ):

            idle_rounds += 1

            print(
                f"连续空闲："
                f"{idle_rounds}/"
                f"{MAX_IDLE_ROUNDS}"
            )

        else:
            idle_rounds = 0

        if idle_rounds >= MAX_IDLE_ROUNDS:
            print()
            print(
                "连续多轮没有新的转发数据, 停止滚动"
            )
            break

    save_progress(
        users,
        checked_users
    )

    print()
    print("=" * 70)
    print("收集转发用户完成")
    print("=" * 70)

    print(
        f"累计不同转发用户："
        f"{len(users)}"
    )

    return users



#检查单个UID
def check_common_following(
    page,
    uid
):

    url = (
        "https://m.weibo.cn/p/index"
        f"?containerid="
        f"231051_-_followers_-_{uid}"
    )

    try:
        print(
            f"访问：{url}"
        )

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=30000
        )

        page.wait_for_timeout(
            COMMON_FOLLOW_WAIT
        )

        count = page.get_by_text(
            "我们的共同关注",
            exact=True
        ).count()

        if count > 0:
            return True
        else:
            return False

    except Exception as e:
        print(
            f"访问 UID {uid} 时发生错误："
        )
        print(e)

        return None



#检查所有 UID
def check_all_common_following(
    page,
    users,
    checked_users
):
    total = len(users)

    print()
    print("=" * 70)
    print("检查共同关注")
    print("=" * 70)

    print(
        f"转发用户总数：{total}"
    )

    print(
        f"已经检查："
        f"{len(checked_users)}"
    )

    for index, (uid, name) in enumerate(
        users.items(),
        start=1
    ):

        if uid in checked_users:

            old_result = checked_users[
                uid
            ]

            print()
            print(
                f"[{index}/{total}] "
                f"UID={uid} "
                f"用户={name}"
            )

            print(
                "已经有检查结果，跳过。"
            )

            continue

        print()
        print("=" * 70)

        print(
            f"[{index}/{total}] "
            f"检查 UID={uid}"
        )

        print(
            f"用户：{name}"
        )

        result = None

        for attempt in range(
            1,
            MAX_RETRIES + 1
        ):

            print(
                f"尝试 "
                f"{attempt}/"
                f"{MAX_RETRIES}"
            )

            result = check_common_following(
                page,
                uid
            )

            if result is not None:
                break

            if attempt < MAX_RETRIES:
                print(
                    f"{RETRY_WAIT / 1000:.1f}"
                    f" 秒后重试..."
                )
                time.sleep(
                    RETRY_WAIT / 1000
                )

        if result is True:
            print(
                ">>> 存在共同关注"
            )

            checked_users[uid] = {
                "name": name,
                "common_following": True,
                "status": "success"
            }

        elif result is False:
            print(
                "没有共同关注"
            )

            checked_users[uid] = {
                "name": name,
                "common_following": False,
                "status": "success"
            }

        else:
            print(
                "多次尝试仍然失败"
            )

            checked_users[uid] = {
                "name": name,
                "common_following": None,
                "status": "failed"
            }

        save_progress(
            users,
            checked_users
        )

        print(
            "进度已经保存。"
        )


def export_csv(
    users,
    checked_users
):

    with CSV_FILE.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.writer(f)

        writer.writerow([
            "UID",
            "用户名",
            "是否存在共同关注",
            "检查状态"
        ])

        for uid, name in users.items():
            result = checked_users.get(
                uid
            )

            if result is None:
                common_following = ""
                status = "未检查"

            else:
                common_following = (
                    result.get(
                        "common_following"
                    )
                )

                if common_following is True:
                    common_following = "是"

                elif common_following is False:
                    common_following = "否"

                else:
                    common_following = ""

                status = result.get(
                    "status",
                    ""
                )

            writer.writerow([
                uid,
                name,
                common_following,
                status
            ])

    print()
    print("=" * 70)
    print("CSV 导出完成")
    print("=" * 70)

    print(
        f"文件："
        f"{CSV_FILE.resolve()}"
    )


def print_final_result(
    users,
    checked_users
):
    common_users = {}

    for uid, result in (
        checked_users.items()
    ):

        if (
            result.get(
                "common_following"
            )
            is True
        ):

            common_users[uid] = (
                result.get(
                    "name",
                    users.get(uid)
                )
            )

    failed_count = 0

    for result in checked_users.values():

        if result.get(
            "status"
        ) == "failed":

            failed_count += 1

    print()
    print("=" * 70)
    print("最终结果")
    print("=" * 70)

    print(
        f"转发用户总数："
        f"{len(users)}"
    )

    print(
        f"已经检查："
        f"{len(checked_users)}"
    )

    print(
        f"存在共同关注："
        f"{len(common_users)}"
    )

    print(
        f"检查失败："
        f"{failed_count}"
    )

    print()

    if not common_users:

        print(
            "目前没有找到存在共同关注的用户。"
        )

        return

    print(
        "存在共同关注的用户："
    )

    print()

    for index, (uid, name) in enumerate(
        common_users.items(),
        start=1
    ):

        print(
            f"{index:4d}. "
            f"UID: {uid:<12} "
            f"用户: {name}"
        )


def main():
    users, checked_users = (
        load_progress()
    )

    with sync_playwright() as p:
        context = (
            p.chromium.launch_persistent_context(
                user_data_dir=str(
                    USER_DATA_DIR
                ),
                headless=False,
                channel="chrome",
                viewport=None,
            )
        )

        if context.pages:
            page = context.pages[0]

        else:
            page = context.new_page()

        try:
            users = collect_repost_users(
                page,
                users,
                checked_users
            )

            check_all_common_following(
                page,
                users,
                checked_users
            )

            export_csv(
                users,
                checked_users
            )

            print_final_result(
                users,
                checked_users
            )

            input(
                "\n按 Enter 关闭浏览器..."
            )

        finally:
            context.close()

if __name__ == "__main__":
    main()