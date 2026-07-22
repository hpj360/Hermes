"""IBA 经典鸡尾酒配方种子数据（M3 MVP 8 款）。

每款配方作为 Markdown 文档导入知识库（category=recipe）。
ingredients 字段为标准化材料名列表（用于匹配算法）。
"""
from __future__ import annotations

SEED_RECIPES: list[dict] = [
    {
        "title": "马天尼 Martini",
        "base_spirit": "gin",
        "difficulty": "easy",
        "season": "autumn",
        "ingredients": ["金酒", "味美思", "橄榄"],
        "content": """# 马天尼 Martini

## 配方
- 金酒 60ml
- 干味美思 10ml
- 橄榄 1 颗（装饰）

## 步骤
1. 冰镇马天尼杯
2. 调酒杯加冰，倒入金酒与味美思
3. 搅拌 30 秒
4. 滤冰倒入杯中
5. 放入橄榄

## 风味
干爽、清冽、杜松子主导。被誉为"鸡尾酒之王"。
""",
    },
    {
        "title": "莫吉托 Mojito",
        "base_spirit": "rum",
        "difficulty": "easy",
        "season": "summer",
        "ingredients": ["朗姆酒", "青柠汁", "糖浆", "薄荷叶", "苏打水"],
        "content": """# 莫吉托 Mojito

## 配方
- 白朗姆酒 45ml
- 青柠汁 20ml
- 糖浆 15ml
- 薄荷叶 8-10 片
- 苏打水 适量

## 步骤
1. 薄荷叶与糖浆放入杯中轻轻捣压
2. 加入青柠汁与朗姆酒
3. 加碎冰至八分满
4. 注入苏打水至满
5. 搅拌提升，以薄荷枝装饰

## 风味
清新、薄荷凉爽、酸甜平衡。夏日经典长饮。
""",
    },
    {
        "title": "尼格罗尼 Negroni",
        "base_spirit": "gin",
        "difficulty": "easy",
        "season": "autumn",
        "ingredients": ["金酒", "金巴利", "味美思", "橙皮"],
        "content": """# 尼格罗尼 Negroni

## 配方
- 金酒 30ml
- 金巴利 30ml
- 甜味美思 30ml
- 橙皮 1 片（装饰）

## 步骤
1. 古典杯加冰
2. 倒入金酒、金巴利、甜味美思
3. 搅拌 20 秒
4. 橙皮扭拧释放精油，装饰

## 风味
苦甜平衡、药草香、酒体饱满。等比经典。
""",
    },
    {
        "title": "玛格丽特 Margarita",
        "base_spirit": "tequila",
        "difficulty": "medium",
        "season": "summer",
        "ingredients": ["龙舌兰", "君度", "青柠汁", "柠檬片"],
        "content": """# 玛格丽特 Margarita

## 配方
- 龙舌兰 50ml
- 君度 20ml
- 青柠汁 20ml
- 盐边 + 柠檬片装饰

## 步骤
1. 杯口蘸半圈盐边
2. 冰块加入摇酒壶
3. 倒入龙舌兰、君度、青柠汁
4. 摇匀 15 秒
5. 滤入盐边杯，柠檬片装饰

## 风味
酸甜咸三味平衡，龙舌兰植物香突出。墨西哥国饮。
""",
    },
    {
        "title": "古典鸡尾酒 Old Fashioned",
        "base_spirit": "whiskey",
        "difficulty": "easy",
        "season": "winter",
        "ingredients": ["威士忌", "糖浆", "苦精", "橙皮"],
        "content": """# 古典鸡尾酒 Old Fashioned

## 配方
- 波本威士忌 60ml
- 糖浆 5ml
- 苦精 2 滴
- 橙皮 1 片（装饰）

## 步骤
1. 古典杯加糖浆与苦精
2. 加冰块
3. 倒入威士忌
4. 搅拌 20 秒
5. 橙皮释放精油装饰

## 风味
醇厚、威士忌主导、微甜。最古老的经典配方之一。
""",
    },
    {
        "title": "白色佳人 White Lady",
        "base_spirit": "gin",
        "difficulty": "medium",
        "season": "spring",
        "ingredients": ["金酒", "君度", "柠檬汁"],
        "content": """# 白色佳人 White Lady

## 配方
- 金酒 40ml
- 君度 15ml
- 柠檬汁 20ml

## 步骤
1. 摇酒壶加冰
2. 倒入金酒、君度、柠檬汁
3. 摇匀 15 秒
4. 滤冰倒入冰镇马天尼杯

## 风味
酸香优雅、杜松与橙香交织。酸酒变体经典。
""",
    },
    {
        "title": "龙舌兰日出 Tequila Sunrise",
        "base_spirit": "tequila",
        "difficulty": "easy",
        "season": "summer",
        "ingredients": ["龙舌兰", "橙汁", "糖浆"],
        "content": """# 龙舌兰日出 Tequila Sunrise

## 配方
- 龙舌兰 45ml
- 橙汁 90ml
- 红石榴糖浆 15ml

## 步骤
1. 高球杯加冰
2. 倒入龙舌兰与橙汁，搅拌
3. 沿杯壁缓缓倒入红石榴糖浆
4. 使其沉底形成日出渐层
5. 饮用前搅拌

## 风味
果香甜美、视觉渐层。日出色彩由此得名。
""",
    },
    {
        "title": "血腥玛丽 Bloody Mary",
        "base_spirit": "vodka",
        "difficulty": "easy",
        "season": "winter",
        "ingredients": ["伏特加", "番茄汁", "柠檬汁", "苦精"],
        "content": """# 血腥玛丽 Bloody Mary

## 配方
- 伏特加 45ml
- 番茄汁 90ml
- 柠檬汁 15ml
- 苦精 2 滴
- 盐、黑胡椒、辣椒酱适量

## 步骤
1. 高球杯加冰
2. 倒入伏特加、番茄汁、柠檬汁
3. 加苦精与调味料
4. 搅拌均匀
5. 芹菜枝或柠檬片装饰

## 风味
咸鲜辛辣、番茄浓郁。宿醉救星传说。
""",
    },
]
