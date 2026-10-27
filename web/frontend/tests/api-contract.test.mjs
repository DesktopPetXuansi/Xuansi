import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, relative, resolve, sep } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const apiFile = resolve(frontend, "src/lib/api.ts");
const slot = "\u0000";
const methods = new Set([
  "get",
  "post",
  "put",
  "patch",
  "delete",
  "head",
  "options",
  "trace",
]);

function unique(values) {
  return [...new Set(values)];
}

function finiteStrings(type) {
  if (!type) return undefined;
  if (type.isStringLiteral()) return [type.value];
  if (type.isUnion()) {
    const choices = type.types.map(finiteStrings);
    if (choices.every(Boolean)) return unique(choices.flat());
  }
}

// 只展开请求表达式，不执行业务源码。未知值只能占契约已声明的参数段。
function values(node, checker, seen = new Set()) {
  if (!node || seen.has(node)) return [slot];
  seen = new Set(seen).add(node);
  const expand = (child) => values(child, checker, seen);
  if (ts.isStringLiteralLike(node)) return [node.text];
  if (
    ts.isParenthesizedExpression(node) ||
    ts.isAsExpression(node) ||
    ts.isNonNullExpression(node)
  )
    return expand(node.expression);
  if (ts.isConditionalExpression(node))
    return unique([...expand(node.whenTrue), ...expand(node.whenFalse)]);
  if (ts.isTemplateExpression(node)) {
    let result = [node.head.text];
    for (const span of node.templateSpans) {
      if (result.every((prefix) => prefix.includes("?"))) break;
      const suffixes = expand(span.expression);
      result = unique(
        result.flatMap((prefix) =>
          prefix.includes("?")
            ? [prefix]
            : suffixes.map((suffix) => prefix + suffix + span.literal.text),
        ),
      );
    }
    return result;
  }
  if (
    ts.isBinaryExpression(node) &&
    node.operatorToken.kind === ts.SyntaxKind.PlusToken
  ) {
    const left = expand(node.left);
    if (left.every((prefix) => prefix.includes("?"))) return left;
    return unique(
      left.flatMap((prefix) =>
        prefix.includes("?")
          ? [prefix]
          : expand(node.right).map((suffix) => prefix + suffix),
      ),
    );
  }
  if (checker) {
    const finite = finiteStrings(checker.getTypeAtLocation(node));
    if (finite) return finite;
    const symbol = checker.getSymbolAtLocation(node);
    const declaration = symbol?.valueDeclaration;
    if (
      declaration &&
      ts.isVariableDeclaration(declaration) &&
      declaration.initializer &&
      declaration.parent.flags & ts.NodeFlags.Const
    )
      return expand(declaration.initializer);
  }
  return [slot];
}

function matches(path, documented) {
  const requested = path.split("?")[0].split("/");
  const segments = documented.split("/");
  return (
    requested.length === segments.length &&
    segments.every((part, index) =>
      part.startsWith("{") && part.endsWith("}")
        ? requested[index].length > 0
        : part === requested[index],
    )
  );
}

function contractRoutes(specification) {
  return Object.entries(specification.paths).flatMap(([path, operations]) =>
    Object.keys(operations)
      .filter((method) => methods.has(method))
      .map((method) => ({ path, method: method.toUpperCase() })),
  );
}

function checkCall(call, name, checker, routes) {
  const paths = values(call.arguments[0], checker).map(
    (path) => `/api/v1${path.split("?")[0]}`,
  );
  const requestedMethods =
    name === "apiPage" || !call.arguments[1]
      ? ["GET"]
      : values(call.arguments[1], checker);
  const supports = (path, method) =>
    routes.some(
      (route) => route.method === method && matches(path, route.path),
    );
  for (const path of paths) {
    assert.ok(
      !path.slice("/api/v1".length).startsWith(slot),
      "完整请求路径或前缀无法静态确认，请使用有限的路径类型",
    );
    assert.ok(
      requestedMethods.some((method) => supports(path, method)),
      `没有匹配的接口：${requestedMethods.join("|")} ${path.replaceAll(slot, "{参数}")}`,
    );
  }
  for (const method of requestedMethods)
    assert.ok(
      paths.some((path) => supports(path, method)),
      `没有匹配的请求方法：${method.replaceAll(slot, "{未知}")}`,
    );
}

function checkExample(source, name = "api") {
  const file = ts.createSourceFile(
    "contract-fixture.ts",
    source,
    ts.ScriptTarget.Latest,
    true,
  );
  checkCall(file.statements[0].expression, name, undefined, exampleRoutes);
}

const exampleRoutes = [
  { path: "/api/v1/resources", method: "GET" },
  { path: "/api/v1/resources/{id}", method: "GET" },
];

test("请求契约门禁拒绝虚构路径和错误 HTTP 方法", () => {
  for (const source of [
    'api("/missing")',
    'api("/resources", "DELETE")',
    'api("/resources", method)',
  ])
    assert.throws(() => checkExample(source), /没有匹配/);
});

test("未知前缀不能伪装成已声明的静态路由", () => {
  assert.throws(() => checkExample("api(endpoint)"), /无法静态确认/);
  assert.throws(() => checkExample("api(`/${endpoint}`)"), /没有匹配的接口/);
});

test("参数段、条件路径与查询串沿用同一请求校验", () => {
  checkExample('api(id ? `/resources/${id}?limit=${limit}` : "/resources")');
  checkExample('apiPage("/resources?kind=MODEL", options)', "apiPage");
});

test("真实前端 api/apiPage 可静态展开的请求路径与方法匹配 OpenAPI", () => {
  const configPath = resolve(frontend, "tsconfig.json");
  const loaded = ts.readConfigFile(configPath, ts.sys.readFile);
  assert.equal(loaded.error, undefined);
  const config = ts.parseJsonConfigFileContent(loaded.config, ts.sys, frontend);
  assert.equal(config.errors.length, 0);
  const program = ts.createProgram(config.fileNames, config.options);
  const checker = program.getTypeChecker();
  const specification = JSON.parse(
    readFileSync(resolve(frontend, "../contracts/openapi.yaml"), "utf8"),
  );
  const routes = contractRoutes(specification);
  const failures = [];
  let checked = 0;
  for (const file of program.getSourceFiles()) {
    const path = resolve(file.fileName);
    if (
      file.isDeclarationFile ||
      !path.startsWith(resolve(frontend, "src") + sep)
    )
      continue;
    if (path === apiFile) continue;
    const visit = (node) => {
      if (ts.isCallExpression(node)) {
        let symbol = checker.getSymbolAtLocation(node.expression);
        if (symbol?.flags & ts.SymbolFlags.Alias)
          symbol = checker.getAliasedSymbol(symbol);
        const name = symbol?.getName();
        if (
          (name === "api" || name === "apiPage") &&
          symbol.declarations?.some(
            (declaration) =>
              resolve(declaration.getSourceFile().fileName) === apiFile,
          )
        ) {
          checked++;
          try {
            checkCall(node, name, checker, routes);
          } catch (error) {
            const { line } = file.getLineAndCharacterOfPosition(
              node.getStart(file),
            );
            failures.push(
              `${relative(frontend, path)}:${line + 1} ${error.message}`,
            );
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(file);
  }
  assert.ok(checked > 0, "没有找到真实 API 调用，检查器不能空跑通过");
  console.info(
    `[请求契约] 核对 ${checked} 个真实调用点；范围为 api/apiPage 路径与方法，不含泛型转发、回执上传 URL、响应正文或条件分支相关性。`,
  );
  assert.deepEqual(failures, []);
});
