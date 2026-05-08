---
name: "weather"
description: "查询用户指定城市或地区的实时天气、未来天气和简短出行建议。"
triggers:
- 天气
- 今天天气
- 实时天气
- 温度
- 气温
- 降雨
- 下雨
- 风力
- 体感
- 穿衣
- 出行建议
- weather
- forecast
- temperature
- rain
---

# Weather Skill

当用户询问天气、温度、降雨、风力、体感、穿衣建议、未来几天天气时，优先使用本 skill 的脚本查询实时信息，而不是凭空猜测。

## Tool Choice

优先使用统一 skill 脚本执行工具：

```text
run_skill_script(skill_name="weather", script_path="scripts/query_weather.py", arguments=["LOCATION"], timeout_seconds=60)
```

将 `LOCATION` 替换为用户提供的城市或地区英文名、拼音或中文名，例如：

- `武汉`
- `Beijing`
- `Shanghai`
- `Guangzhou`
- `Shenzhen`
- `Hangzhou`

如果用户没有提供地点，默认使用 `Wuhan`。

脚本会通过 `wttr.in` 获取天气 JSON，并输出结构化摘要。不要直接用 `exec` 拼 PowerShell/curl 命令，除非 `run_skill_script` 不可用。

## Response Rules

拿到结果后，优先提炼这些信息：

- 当前天气描述
- 当前温度与体感温度
- 降雨概率
- 风速或风力
- 今天或未来 1-3 天趋势

## Important

- 如果天气查询失败，要明确说明失败，并请用户补充更具体的位置。
- 失败时要依据脚本返回的 `status=error`、`error`、`suggestion` 回答，不要伪造天气。
- 不要原样输出整段 JSON，应整理成自然语言摘要。
- 如果用户只问“今天天气怎么样”，默认回答当前天气并补一句今日趋势。

## Fallback Policy

- `query_weather.py` 失败时，说明网络、服务或地点解析失败，不要编造实时天气。
- 如果用户没有提供地点，默认使用 `Wuhan`；如果地点解析异常，请用户补充城市名或拼音。
- 不要反复用 `exec`、curl 或 PowerShell 手动查询，除非 `run_skill_script` 不可用。
- 如果脚本执行成功且结果足够回答用户，停止继续调用工具，直接总结真实结果。
