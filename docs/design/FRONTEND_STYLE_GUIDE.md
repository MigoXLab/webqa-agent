# WebQA Agent 平台前端样式规范

*版本: v1.0*
*最后更新: 2026-02-13*

---

## 一、技术栈

| 项目 | 技术 |
|------|------|
| 框架 | React 18 + TypeScript |
| 构建 | Vite |
| CSS | Tailwind CSS v4.1.3（预编译静态 CSS） |
| 组件库 | Radix UI 原语 + 自定义封装 |
| 图标 | Lucide React |
| 主题 | CSS 变量 + Tailwind 工具类（无 dark 模式） |

---

## 二、字体

对齐 **Tailwind CSS 默认**字体栈，与报告页保持一致。

### 正文字体 (`--font-sans`)

```css
ui-sans-serif, system-ui, sans-serif, "Apple Color Emoji", "Segoe UI Emoji",
"Segoe UI Symbol", "Noto Color Emoji"
```

### 代码字体 (`--font-mono`)

```css
ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono",
"Courier New", monospace
```

### 字号层级

| 用途 | Tailwind 类 | 实际大小 |
|------|------------|---------|
| 页面标题 | `text-xl font-semibold` | 20px / 600 |
| 弹窗标题 | `text-lg font-semibold` | 18px / 600 |
| Section 标题 | `text-base font-semibold` | 16px / 600 |
| 正文 / 表单标签 | `text-sm font-medium` | 14px / 500 |
| 辅助文字 / 描述 | `text-xs` | 12px |

---

## 三、色彩体系

### 设计原则

- **所有颜色与报告页完全统一**，均使用 Tailwind CSS v4 默认色板（oklch 色彩空间）
- **蓝色** = 主交互色（按钮、链接、选中态、focus ring）
- **紫色** = 点缀色（标签/徽章、Debug 面板状态）
- **语义色** = 绿/红/黄 仅用于状态指示，不用于交互控件

### 蓝色（主色 - 交互）

| 色阶 | CSS 变量值 (oklch) | 用途 |
|------|-------------------|------|
| blue-50 | `oklch(.97 .014 254.604)` | hover 背景、查看报告按钮 |
| blue-100 | `oklch(.932 .032 255.585)` | Action 步骤标签、信息区背景 |
| blue-200 | `oklch(.882 .059 254.128)` | 边框 |
| blue-500 | `oklch(.623 .214 259.815)` | loading spinner、focus ring |
| blue-600 | `oklch(.546 .245 262.881)` | **主按钮背景**、链接文字、活跃标签 |
| blue-700 | `oklch(.488 .243 264.376)` | 主按钮 hover、标签文字 |
| blue-800 | `oklch(.424 .199 265.638)` | 深色信息文字 |

### 紫色（点缀色 - 标签/Debug）

| 色阶 | CSS 变量值 (oklch) | 用途 |
|------|-------------------|------|
| purple-50 | `oklch(.977 .014 308.299)` | 标签背景、Debug 当前步骤背景 |
| purple-100 | `oklch(.946 .033 307.174)` | Verify 步骤标签、状态徽章背景 |
| purple-200 | `oklch(.902 .063 306.703)` | 标签边框 |
| purple-400 | `oklch(.714 .203 305.504)` | 中间色阶（备用） |
| purple-500 | `oklch(.627 .265 303.9)` | Debug 进度条、spinner、focus ring |
| purple-600 | `oklch(.558 .288 302.321)` | Debug 状态文字 |
| purple-700 | `oklch(.496 .265 301.924)` | 标签文字 |
| purple-800 | `oklch(.438 .218 303.724)` | 深色信息文字 |

### Indigo（渐变辅助色）

| 色阶 | CSS 变量值 (oklch) | 用途 |
|------|-------------------|------|
| indigo-50 | `oklch(.962 .018 272.314)` | 渐变终止色 |
| indigo-100 | `oklch(96.2% .018 272.314)` | 备用 |
| indigo-200 | `oklch(93% .034 272.788)` | 备用 |
| indigo-300 | `oklch(87% .065 274.039)` | 备用 |

### 渐变卡片样式（报告页同款）

```css
/* Tailwind 类 */
bg-gradient-to-r from-purple-50 to-indigo-50 border border-purple-200

/* 对角渐变 */
bg-gradient-to-br from-blue-50 to-indigo-50 border border-blue-100
```

### 语义色（与报告页统一）

| 颜色 | CSS 变量值 (oklch) | 用途 |
|------|-------------------|------|
| green-50 | `oklch(.982 .018 155.826)` | 成功标签背景 |
| green-100 | `oklch(.962 .044 156.743)` | 成功状态徽章背景 |
| green-600 | `oklch(.627 .194 149.214)` | 成功图标/文字 |
| green-700 | `oklch(.527 .154 150.069)` | 成功标签文字 |
| red-50 | `oklch(.971 .013 17.38)` | 失败标签背景 |
| red-100 | `oklch(.936 .032 17.717)` | 失败状态徽章背景 |
| red-200 | `oklch(.885 .062 18.334)` | 失败边框 |
| red-600 | `oklch(.577 .245 27.325)` | 失败图标/停止按钮 |
| red-700 | `oklch(.505 .213 27.518)` | 失败标签文字 |
| yellow-50 | `oklch(.987 .026 102.212)` | 警告背景 |
| yellow-100 | `oklch(.973 .071 103.193)` | 警告状态徽章背景 |
| yellow-600 | `oklch(.681 .162 75.834)` | 警告图标/文字 |
| yellow-700 | `oklch(.554 .135 66.442)` | 警告标签文字 |
| gray-* | (见下表) | 文字、边框、背景、禁用态 |

### 中性色 (Gray)

| 色阶 | CSS 变量值 (oklch) | 用途 |
|------|-------------------|------|
| gray-50 | `oklch(.985 .002 247.839)` | 浅背景、hover |
| gray-100 | `oklch(.967 .003 264.542)` | 分隔线、浅背景 |
| gray-200 | `oklch(.928 .006 264.531)` | 边框、分割线 |
| gray-300 | `oklch(.872 .01 258.338)` | 禁用边框 |
| gray-500 | `oklch(.551 .027 264.364)` | 辅助文字 |
| gray-600 | `oklch(.446 .03 256.802)` | 次级文字 |
| gray-700 | `oklch(.373 .034 259.733)` | 正文文字 |
| gray-800 | `oklch(.278 .033 256.848)` | 深色文字、终端背景 |
| gray-900 | `oklch(.21 .034 264.665)` | 标题文字 |

### 不可用的组合

- ❌ 深绿按钮（`bg-green-600`）做 CTA — 改用蓝色
- ❌ 多种饱和色按钮并排（蓝+绿+红）— 保持单一主色
- ❌ 终端绿色用于非终端 UI 元素

---

## 四、组件样式规范

### 主按钮（CTA）— 实心

```
bg-blue-600 text-white rounded-lg hover:bg-blue-700
text-sm font-medium px-4 py-2
```

适用: 保存、创建、导入、导出、新建用例

### 执行/调试按钮 — 浅色（Ghost）

```
bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100
border border-blue-200 text-sm font-medium px-4 py-2
```

适用: 执行、调试、开始调试、继续

### 停止/删除按钮

```
bg-red-600 text-white rounded-lg hover:bg-red-700
text-sm font-medium px-4 py-2
```

### 次级按钮（Ghost）

```
border border-gray-300 rounded-lg hover:bg-gray-50
text-sm font-medium text-gray-700
```

适用: 取消、关闭、不保存离开

### 文字按钮/链接

```
text-blue-600 hover:text-blue-700 text-sm font-medium
```

适用: 添加环境、添加步骤、查看详情

### 返回导航

```
flex items-center gap-1.5 text-gray-500 hover:text-gray-900
transition-colors text-sm
```
图标: `ArrowLeft w-4 h-4`

### Case 标签/徽章

**蓝色标签**（🔑 需登录）:
```
bg-blue-50 text-blue-700 rounded-lg text-xs font-medium
border border-blue-200 px-3 py-1.5
```

**紫色标签**（🏷️ 版本号）:
```
bg-purple-50 text-purple-700 rounded-lg text-xs font-medium
border border-purple-200 px-3 py-1.5
```

**灰色标签**（📸 快照 / 🔄 使用快照）:
```
bg-gray-50 text-gray-500 rounded-lg text-xs font-medium
border border-gray-200 px-3 py-1.5
```

**灰色标签（未激活）**（🔓 免登录）:
```
bg-gray-50 text-gray-400 rounded-lg text-xs font-medium
border border-gray-200 px-3 py-1.5
```

### 步骤类型标签

**蓝色**（Action 步骤）:
```
bg-blue-100 text-blue-700 rounded text-xs font-medium
px-2 py-0.5
```

**紫色**（Verify 步骤）:
```
bg-purple-100 text-purple-700 rounded text-xs font-medium
px-2 py-0.5
```

### 活跃标签指示器（Tab）

```
border-b-2 border-blue-600 text-blue-600 text-sm font-medium
```

### 输入框 Focus

```
focus:ring-2 focus:ring-blue-500 focus:border-blue-500
```

### 状态徽章

| 状态 | 样式 |
|------|------|
| 通过 | `bg-green-100 text-green-700 rounded-full` |
| 失败 | `bg-red-100 text-red-700 rounded-full` |
| 运行中 | `bg-blue-100 text-blue-700 rounded-full` |
| 等待 | `bg-gray-100 text-gray-700 rounded-full` |
| 超时 | `bg-orange-100 text-orange-700 rounded-full` |

### Debug 面板（蓝色系）

| 元素 | 样式 |
|------|------|
| 执行中脉冲点 | `bg-blue-500 rounded-full animate-pulse` |
| 执行中文字 | `text-blue-600` |
| 步骤 spinner | `border-blue-500 border-t-transparent animate-spin` |
| 进度条 | `bg-blue-500 h-1 rounded-full` |
| 当前步骤高亮 | `border-blue-500 bg-blue-50` |
| 执行成功 | `text-green-600`（语义色，保持） |
| 终端日志 | `bg-gray-900 text-green-400 font-mono`（终端风格，保持） |

---

## 五、CSS 变量（主题）

定义在 `frontend/src/index.css` 的 `:root` 中:

```css
:root {
  /* 品牌/交互 */
  --primary: #030213;
  --primary-foreground: oklch(1 0 0);

  /* 中性 */
  --background: #fff;
  --foreground: oklch(.145 0 0);
  --border: #0000001a;
  --muted: #ececf0;
  --muted-foreground: #717182;

  /* 语义 */
  --destructive: #d4183d;
  --destructive-foreground: #fff;

  /* 控件 */
  --ring: oklch(.708 0 0);
  --radius: .625rem;
}
```

---

## 六、页面标题层级

| 组件 | 标题内容 | 样式 |
|------|---------|------|
| TestCaseManager | 业务名称 | `text-xl font-semibold` |
| CaseEditorPage | 新建用例 / 编辑用例 | `text-xl font-semibold` |
| ExecutionHistory | 执行历史 | `text-xl font-semibold` |
| ExecutionDetail | 任务 ID: xxx | `text-xl font-semibold` |
| DebugPanel | 用例名称 | `text-xl font-semibold` |
| 弹窗 (Modal/Drawer) | 标题 | `text-lg font-semibold` |

---

## 七、文件索引

| 文件 | 说明 |
|------|------|
| `frontend/src/index.css` | 全局样式、CSS 变量、颜色定义、工具类 |
| `frontend/src/styles/globals.css` | Tailwind v4 主题源文件（当前未引入） |
| `frontend/src/components/TestCaseManager.tsx` | 用例列表页 |
| `frontend/src/components/CaseEditorPage.tsx` | 用例编辑页 |
| `frontend/src/components/ExecutionHistory.tsx` | 执行历史页 |
| `frontend/src/components/ExecutionDetail.tsx` | 执行详情页 |
| `frontend/src/components/DebugPanel.tsx` | Debug 调试面板 |
| `frontend/src/components/BusinessManager.tsx` | 业务管理（首页+弹窗） |
| `frontend/src/components/ScheduledTaskManager.tsx` | 定时任务管理 |
| `frontend/src/components/FileManager.tsx` | 文件管理弹窗 |
| `frontend/src/components/ConfigImportExport.tsx` | 配置导入导出弹窗 |
