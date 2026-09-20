/**
 * 前端入口 main.ts —— 应用启动的唯一入口（对应 index.html 里的 <script type="module" src="/src/main.ts">）。
 * 职责只有四件事：引入全局样式 → 注册 Vant 组件 → 装配路由 → 把根组件挂载到 #app。
 * 本文件不写任何业务逻辑，只负责「装配」，业务都在 views/ 与 composables/ 里。
 */

// Vue 核心 API：createApp 用来创建应用实例，后面的 .use() / .mount() 都挂在它返回的实例上
import {createApp} from 'vue'

// 根组件：整个页面的挂载点，内部负责顶部导航与 <RouterView> 路由出口
import App from './App.vue'
// 路由实例：包含首页 / 关于 / 扫描等路由表，本文件把它注册成全局插件（模板里才能用 RouterLink/RouterView）
import router from './router'
// Pinia 状态管理：本项目设置页等需要全局状态的模块通过它共享数据；createPinia 返回的实例需在挂载前 .use() 注册
import { createPinia } from 'pinia'
// 全局基础样式：定义 --color-primary 等 CSS 变量和基础排版，各组件样式都依赖这些变量
import './styles/main.css'
// Vant 组件库的全量样式：本项目组件是下方逐个 .use() 按需注册的，但样式一次性全量引入，省去逐个补样式
import 'vant/lib/index.css';
/*
 * Vant（移动端 UI 组件库）组件注册清单：这些组件必须在应用启动时注册，之后任意组件模板里才能直接写 <van-xxx>。
 * 逐项说明它们在本项目里承担什么职责：
 *   Form / Field         —— 表单容器与表单项（设置、导入类页面）
 *   Cell / CellGroup     —— 列表单元格与分组，文件列表用它排版
 *   Search               —— 顶部搜索框（扫描结果页）
 *   DropdownMenu / DropdownItem —— 下拉筛选与排序菜单
 *   Button               —— 通用按钮
 *   Uploader             —— 文件上传
 *   Loading              —— 加载中占位
 *   Empty                —— 空数据占位
 *   Tag                  —— 小标签（如「已选 N 项」）
 *   Icon                 —— 图标
 *   Checkbox             —— 多选框（文件多选）
 *   NoticeBar            —— 横向通知/提示条
 *   List                 —— 长列表与触底加载
 *   Popup                —— 弹出层容器（工作区选择等）
 *   Popover              —— 气泡弹出菜单（文件胶囊的「打开方式」）
 *   Switch               —— 设置页布尔型开关（按 SettingDef.type='bool' 自动渲染）
 *   Toast / Dialog       —— 设置页反馈：Toast 给操作成功的轻提示，Dialog 删除前确认弹窗
 */
import {
  Form,
  Field,
  Cell,
  CellGroup,
  Search,
  DropdownMenu,
  DropdownItem,
  Button,
  Uploader,
  Loading,
  Empty,
  Tag,
  Icon,
  Checkbox,
  NoticeBar,
  List,
  Popup,
  Popover,
  Switch,
  Toast,
  Dialog,
} from 'vant';


// 创建应用实例 → 装配路由与上面那批 Vant 组件 → 挂载到 index.html 中 id 为 app 的容器节点上
createApp(App)
    .use(router)
    .use(createPinia())
    .use(Form)
    .use(Field)
    .use(Cell)
    .use(CellGroup)
    .use(Search)
    .use(Uploader)
    .use(DropdownMenu)
    .use(DropdownItem)
    .use(Button)
    .use(Loading)
    .use(Empty)
    .use(Tag)
    .use(Icon)
    .use(Checkbox)
    .use(NoticeBar)
    .use(List)
    .use(Popup)
    .use(Popover)
    .use(Switch)
    .use(Toast)
    .use(Dialog)
    .mount('#app')
