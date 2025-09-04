#!/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

# 获取到期的任务，并通过 jq 解析JSON
tasks=$(task +PENDING due.before:+30min export | jq -c '.[]')

# 如果有到期任务，显示通知
if [ "$tasks" != "[]" ]; then
    # 初始化消息
    message=""

    # 使用子 shell 保留变量值
    while IFS= read -r task; do
        description=$(echo "$task" | jq -r '.description')
        due=$(echo "$task" | jq -r '.due')

        # 检查是否有描述和 due 时间
        if [ -n "$description" ] && [ -n "$due" ]; then
            # 获取当前时区
            timezone=$(date +%z)
            
            # 提取时区的小时和分钟部分
            timezone_hours=${timezone:1:2}
            timezone_minutes=${timezone:3:2}
            
            # 将 UTC 时间转换为本地时间
            due_local=$(date -u -jf "%Y%m%dT%H%M%SZ" -v +"$timezone_hours"H -v +"$timezone_minutes"M -f "%Y%m%dT%H%M%SZ" "$due" "+%Y-%m-%d %H:%M:%S" 2>/dev/null)
            
            # 检查时间转换是否成功
            if [ $? -eq 0 ]; then
                # 将任务添加到消息中
                message+="$description due $due_local\n"
            else
                message+="$description due date format error\n"
            fi
        fi
    done <<< "$tasks"

    # 检查是否有消息
    if [ -n "$message" ]; then
        # 使用 osascript 显示通知
        osascript -e "display notification \"$message\" with title \"Taskwarrior Reminder\""
    fi
fi

