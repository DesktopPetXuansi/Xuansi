// 选择框与尺寸角标参考 delineate Assembly 的 Frame 实现，MIT 许可见第三方声明。
export function createAssemblyFrame(target: HTMLElement, layer: HTMLElement) {
  const element = document.createElement("div");
  element.className = "assembly-frame";
  for (const corner of [
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
  ]) {
    const handle = document.createElement("i");
    handle.className = `assembly-handle ${corner}`;
    element.append(handle);
  }
  const badge = document.createElement("span");
  badge.className = "assembly-badge";
  element.append(badge);
  layer.append(element);

  // 框线随滚动更新，只读取尺寸，不读取或复制页面中的输入内容。
  function update(box = target.getBoundingClientRect()) {
    Object.assign(element.style, {
      left: `${box.left}px`,
      top: `${box.top}px`,
      width: `${box.width}px`,
      height: `${box.height}px`,
    });
    badge.textContent = `${Math.round(box.width)} × ${Math.round(box.height)}`;
  }
  update();
  return { element, update };
}
