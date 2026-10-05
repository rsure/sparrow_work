<!-- components/PanelCard.vue：只有外壳，内容由父决定 -->
<!--
组件说明：通用「面板卡片」外壳，本身不持有任何状态、不发请求，是典型的纯布局 / 展示组件。
它只提供三段结构，父组件把内容塞进对应插槽即可复用同一套边框与间距：
  ① #header  具名插槽（可选）—— 卡片标题栏，父组件不传时整个 header 不渲染；
  ② 默认插槽            —— 卡片主体，必填区域；
  ③ #footer  具名插槽（可选）—— 卡片底部操作区，同样按需渲染。
用法示例：<PanelCard><template #header>标题</template>主体内容</PanelCard>
-->
<!--
📚 背景知识：v-model 到底是干什么的
v-model 全称「双向绑定」（two-way binding），本质是给「一份数据」和「一个输入控件」建立同步关系：
数据变了，控件显示的值跟着变；用户操作控件（打字、勾选、拖动），数据也立刻跟着变。
在原生表单元素上（<input>/<select>/<textarea>），v-model="x" 是这样一句话的语法糖：
:value="x" @input="x = $event.target.value"（checkbox/radio 略有不同，见 10.5）。
没有 v-model 之前，你要自己写「取值 → 存到 ref → 再把 ref 塞回控件」这一整套样板代码，
v-model 帮你把这套样板压缩成一个指令。
在自定义组件上，v-model 不是操作 DOM 控件，而是「传一个 prop + 监听一个 update 事件」的语法糖
（下面马上讲），这也是为什么它能出现在 <SearchBar v-model:keyword="keyword" /> 这种自定义组件身上。
官方文档：指南 · 表单输入绑定（原生表单）·
指南 · 组件上的 v-model（自定义组件）
 -->
<template>
  <section class="panel">
    <!-- $slots.header 判断父组件是否真的传了表头插槽：没传就不渲染空标题栏 -->
    <header v-if="$slots.header" class="panel__header"><slot name="header" /></header>
    <!-- 默认插槽：卡片主体，父组件写在 <PanelCard> 里的内容落到这里 -->
    <div class="panel__body"><slot /></div>
    <!-- 同上：父组件没传底部插槽就不渲染页脚 -->
    <footer v-if="$slots.footer" class="panel__footer"><slot name="footer" /></footer>
  </section>
</template>
