import sys
import os
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen

from time import sleep

from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


LOG_FILE = "log.txt"
TIMEZONE = "Asia/Shanghai"


def get_accounts():
    """
    优先从命令行参数读取账号；
    如果没有命令行参数，则从环境变量 EMAIL 和 PASSWD 读取。

    命令行格式：
    python login.py email1 email2 password1 password2

    环境变量格式：
    EMAIL="email1 email2"
    PASSWD="password1 password2"
    """

    # 兼容原来的命令行方式
    if len(sys.argv) > 1:
        args = sys.argv[1:]

        if len(args) % 2 != 0:
            raise RuntimeError(
                "命令行参数数量必须是偶数，前半部分是邮箱，后半部分是密码"
            )

        account_count = len(args) // 2

        emails = args[:account_count]
        passwords = args[account_count:]

    # GitHub Actions 使用环境变量
    else:
        emails = os.environ.get("EMAIL", "").split()
        passwords = os.environ.get("PASSWD", "").split()

    if not emails:
        raise RuntimeError("没有读取到 EMAIL")

    if not passwords:
        raise RuntimeError("没有读取到 PASSWD")

    if len(emails) != len(passwords):
        raise RuntimeError(
            f"邮箱数量和密码数量不一致："
            f"{len(emails)} 个邮箱，{len(passwords)} 个密码"
        )

    return emails, passwords


def send_pushplus(
    token,
    current_time,
    run_success,
    success_count,
    total_count,
    execution_time,
    run_day_no,
    success_day_no,
    account_results,
):
    """
    发送 PushPlus 通知。
    PushPlus 推送失败不会影响登录任务本身。
    """

    if not token:
        print("未配置 PUSHPLUS_TOKEN，跳过 PushPlus 推送")
        return

    status_text = "成功" if run_success else "失败"

    account_status_lines = []

    for result in account_results:
        account_no = result["account_no"]
        account_status = "成功" if result["success"] else "失败"
        error_text = result.get("error", "")

        if error_text:
            # 避免推送内容过长
            error_text = error_text[:200]
            account_status_lines.append(
                f"账号 {account_no}：{account_status}，原因：{error_text}"
            )
        else:
            account_status_lines.append(
                f"账号 {account_no}：{account_status}"
            )

    message = (
        f"雀魂自动登录通知\n\n"
        f"日期：{current_time.strftime('%Y-%m-%d')}\n"
        f"时间：{current_time.strftime('%H:%M:%S')}\n"
        f"本次状态：{status_text}\n"
        f"登录成功：{success_count}/{total_count}\n"
        f"运行日期序号：第 {run_day_no} 天\n"
        f"成功日期序号：第 {success_day_no} 天\n"
        f"执行耗时：{execution_time:.2f} 秒\n\n"
        f"账号详情：\n"
        + "\n".join(account_status_lines)
    )

    pushplus_data = {
        "token": token,
        "title": f"雀魂登录：{status_text}",
        "content": message,
        "template": "txt",
    }

    try:
        request = Request(
            "https://www.pushplus.plus/send",
            data=json.dumps(pushplus_data).encode("utf-8"),
            headers={
                "Content-Type": "application/json"
            },
            method="POST",
        )

        with urlopen(request, timeout=20) as response:
            response_text = response.read().decode("utf-8")

        print(f"PushPlus 推送结果：{response_text}")

    except Exception as error:
        print(f"PushPlus 推送失败：{error}")


def load_history():
    """
    读取历史日志。

    日志格式为 JSON Lines：
    每一行都是一条 JSON 记录。
    """

    all_dates = set()
    success_dates = set()

    if not os.path.exists(LOG_FILE):
        return all_dates, success_dates

    with open(LOG_FILE, "r", encoding="utf-8") as log_file:
        for line in log_file:
            line = line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)

                date = record.get("date")

                if not date:
                    continue

                all_dates.add(date)

                if record.get("success_count", 0) > 0:
                    success_dates.add(date)

            except json.JSONDecodeError:
                # 兼容旧日志格式，旧格式无法参与日期统计
                continue

    return all_dates, success_dates


def append_log(record):
    """
    向 log.txt 追加一行 JSON 日志。
    """

    with open(LOG_FILE, "a", encoding="utf-8") as log_file:
        log_file.write(
            json.dumps(record, ensure_ascii=False) + "\n"
        )


def main():
    emails, passwords = get_accounts()
    total_accounts = len(emails)

    print(f"Config {total_accounts} accounts")

    run_start = time.monotonic()
    account_results = []

    for i in range(total_accounts):
        account_no = i + 1
        email = emails[i]
        password = passwords[i]

        driver = None
        success = False
        error_message = ""

        print("----------------------------")
        print(f"Account {account_no}: starting browser...")

        try:
            # 1. 打开浏览器
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1280,800")

            options.add_experimental_option(
                "excludeSwitches",
                ["enable-automation"]
            )
            options.add_experimental_option(
                "useAutomationExtension",
                False
            )

            driver = webdriver.Chrome(options=options)

            driver.get("https://game.maj-soul.net/1/")

            print(f"Account {account_no} loading game...")

            screen = WebDriverWait(driver, 60).until(
                EC.presence_of_element_located(
                    (By.TAG_NAME, "canvas")
                )
            )

            # 等待登录页面和游戏资源加载
            sleep(60)

            # 2. 输入邮箱
            ActionChains(driver) \
                .move_to_element_with_offset(screen, 350, -135) \
                .click() \
                .send_keys(email) \
                .perform()

            sleep(1)

            # 3. 输入密码
            ActionChains(driver) \
                .move_to_element_with_offset(screen, 350, -50) \
                .click() \
                .send_keys(password) \
                .perform()

            sleep(1)

            # 4. 点击登录
            ActionChains(driver) \
                .move_to_element_with_offset(screen, 350, 60) \
                .click() \
                .perform()

            print(f"Account {account_no} entering game...")

            # 等待登录完成
            sleep(25)

            # 5. 点击画面，触发月卡奖励领取
            # 每轮：先点 (-450, 250)，等 5 秒，再点 (0, 195)
            reward_rounds = 2
            reward_interval = 5

            for round_index in range(1, reward_rounds + 1):
                print(
                    f"Account {account_no} reward round "
                    f"{round_index}/{reward_rounds}: click (-450, 250)"
                )

                ActionChains(driver) \
                    .move_to_element_with_offset(screen, -450, 250) \
                    .click() \
                    .perform()

                sleep(reward_interval)

                print(
                    f"Account {account_no} reward round "
                    f"{round_index}/{reward_rounds}: click (0, 195)"
                )

                ActionChains(driver) \
                    .move_to_element_with_offset(screen, 0, 195) \
                    .click() \
                    .perform()

                if round_index < reward_rounds:
                    sleep(reward_interval)

            print(
                f"Account {account_no} clicked reward positions "
                f"{reward_rounds} rounds; "
                f"waiting for reward collection..."
            )

            # 等待奖励请求完成
            sleep(30)

            success = True

            print(
                f"Account {account_no} "
                f"login and reward collection completed"
            )

        except Exception as error:
            error_message = str(error)

            print(
                f"Account {account_no} failed: "
                f"{error_message}"
            )

        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception as error:
                    print(
                        f"Account {account_no} browser close failed: "
                        f"{error}"
                    )

            print(f"Account {account_no} browser closed")

        account_results.append(
            {
                "account_no": account_no,
                "success": success,
                "error": error_message,
            }
        )

    # 本次运行耗时
    execution_time = time.monotonic() - run_start

    current_time = datetime.now(
        ZoneInfo(TIMEZONE)
    )

    today = current_time.strftime("%Y-%m-%d")

    success_count = sum(
        1
        for result in account_results
        if result["success"]
    )

    total_count = len(account_results)

    # 至少一个账号成功，就将本次视为成功
    run_success = success_count > 0

    # 如果你希望所有账号都成功才算成功，
    # 将上一行改成：
    #
    # run_success = success_count == total_count

    # 读取历史运行日期
    all_dates, success_dates = load_history()

    # 同一天重复运行，不重复计算天数
    run_day_no = len(all_dates | {today})

    # 成功日期序号
    success_day_no = len(
        success_dates | ({today} if run_success else set())
    )

    record = {
        "date": today,
        "time": current_time.strftime("%Y-%m-%d %H:%M:%S"),
        "success": run_success,
        "success_count": success_count,
        "total_count": total_count,
        "execution_time": round(execution_time, 2),
        "run_day_no": run_day_no,
        "success_day_no": success_day_no,
        "accounts": account_results,
    }

    # 写入日志
    append_log(record)

    print("----------------------------")
    print("本次运行结果：")
    print(json.dumps(record, ensure_ascii=False, indent=2))

    # 发送 PushPlus
    pushplus_token = os.environ.get(
        "PUSHPLUS_TOKEN",
        ""
    ).strip()

    send_pushplus(
        token=pushplus_token,
        current_time=current_time,
        run_success=run_success,
        success_count=success_count,
        total_count=total_count,
        execution_time=execution_time,
        run_day_no=run_day_no,
        success_day_no=success_day_no,
        account_results=account_results,
    )

    print("任务结束")


if __name__ == "__main__":
    main()
