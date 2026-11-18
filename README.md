# 栖色织研 · 织物染样配方降维审查

36 波段光谱降维、CIELAB 色差确认与复染配方冻结，面向栖色织研 24 人染整研发组。

上游为光谱仪导出的 `reflectance_20261117.csv`，调色师现在用纸样册和 Excel 比对；36 波段难比较、浓度尺度影响距离、超色差配方仍流向车间。系统接管配方—实测染样—复染签批环节，下游车间只接收主管放行配方。

## 启动

```sh
cp .env.example .env
docker compose up -d --build
# 启动自动 seed；也可人工重复执行（只插入缺少的自然键）
docker compose exec -T backend python -m scripts.seed_demo
```

前端 [localhost:18220](http://localhost:18220)，后端 [localhost:19220/docs](http://localhost:19220/docs)，数据库 17720。停止并删除演示数据：`docker compose down -v --remove-orphans`。

|账号|角色|权限|
|---|---|---|
|admin@qise.test|admin 主管|全部录入、计算、确认、最终签批|
|colorist@qise.test|colorist 调色师|配方/染样录入、PCA、试验与色差确认，不能最终批准|
|viewer@qise.test|viewer 观察员|九页与审计记录只读|

演示密码均为 `Dye2026!`。JWT 有效期 8 小时；所有变更通过后端鉴权。数据库密码与 JWT 默认密钥为本地演示配置。

## 业务模块

- 配方目录：三种染料浓度、唯一配方编号与冻结保护；冻结不能改浓度或追加染样。
- 染样登记：配方外键、唯一批号、36 波段 0–1 反射率、CIELAB 实测值。
- PCA 图谱与配对：Redis 队列交给 Python worker，返回 60 个实算坐标、解释方差与重构误差；建立同配方染样复染配对。
- 复染签批：草稿 → 调色师确认 → 主管批准；批准自动冻结关联配方。ΔE>3 的草稿确认后进入退回修色状态，不能批准。

`ΔE76 = sqrt((L1−L2)^2+(a1−a2)^2+(b1−b2)^2)`；门限 3 为模拟工艺规则，PCA 距离不能代替色差判定。PCA 对 36 维反射率用 StandardScaler，二维 PCA / full SVD / random_state=42；重构 MSE 在标准化空间计算。小于三张染样时计算失败。seed `random.Random(42)`，60 张样本、3 个配方。Redis 结果保存 24 小时，共享 artifacts 卷留存 JSON。

## 一天剧本

1. 08:30 调色师登录，检查 DY-021 靛蓝亚麻（A1.8%、B0.4%、C0.2%）。
2. 09:00 核对 `reflectance_20261117.csv` 与 REF-021（L48/a−2/b−25）。
3. 09:30 登记 SAMPLE-021（L48.7/a−1.5/b−24.5，ΔE≈0.995）。
4. 10:00 生成 60 张染样 PCA 图谱，检查解释方差与重构误差。
5. 10:30 建立 REF-021→SAMPLE-021 复染配对。
6. 11:00 以 SAMPLE-OFF（L62/a8/b−14）测试超限，确认后退回修色。
7. 14:00 调色师确认合格试验，主管批准，配方冻结。
8. 16:00 车间观察员查签批簿与审计账号，依据冻结配方安排复染。

## 工程与本地开发

Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL16 / Redis7 / scikit-learn1.6；前端原生 ES modules / HTML / CSS / Nginx1.27。

`backend/src/models.py` 定义领域模型；`schemas.py` 校验输入；`recipe_service.py` 承担领域规则和审计；`app.py` 路由及两道中间件；`atlas.py` 纯 Python ML；`worker.py` 消费队列、记录心跳；`backend/scripts/seed_demo.py` 幂等数据。首次启动 SQLAlchemy metadata 建表，本小型项目不含后续在线迁移工具。

前端 `src/api.js` API、`store.js` 状态、`utils.js` 格式与反馈、`components/common.js` 标题/状态/光谱/证据表、`pages/` 九个业务页面。角色与试验状态枚举分别位于 `backend/src/constants.py` 与 `frontend/src/constants.js`。

本地后端：创建 Python3.12 venv，安装 `backend/requirements.txt`，设置 DATABASE_URL/REDIS_URL 指向映射端口，进入 backend 运行 `uvicorn src.app:app --reload`；worker 同目录运行 `python -m src.worker`（本地 `/artifacts` 路径需有写权限）。本地前端可经现成 Nginx 容器开发，修改后 compose build frontend。

环境变量：COMPOSE_PROJECT_NAME 容器名前缀、FRONTEND_PORT/BACKEND_PORT/DB_PORT 宿主端口、JWT_SECRET 签名密钥、SEED_DEMO 自动 seed；NETWORK_SUBNET 可调整显式私有子网（默认10.221.21.0/24，规避本机默认地址池耗尽）。服务内部 DATABASE_URL、REDIS_URL 由 Compose 指定。五服务均有真实健康检查；db/redis/artifacts 三个命名卷。业务与浏览器验收在源码外 `test-artifacts/gb-1021/`。

## License

MIT，见 LICENSE。


## 业务扩展（2026-11-17）

新增两个独立业务模块，业务数据持久化到 PostgreSQL：

- **配方修订谱系**：冻结父配方复制成新子版本，保存父编号、名称与三染料浓度快照；修订理由必填。主管审核来源前，子版不能改浓度、追加染样或建立复染试验。审核后可独立调整子版，原版继续冻结。子版必须是新编号，拒绝重复子版本与循环关联。
- **生产缸次色差验收**：已批准复染试验才能下生产缸次，保存目标色样快照。登记生产 Lab 后由 Python 实算 ΔE76；超过3进入扣留，可修色后复测；合格后主管签放，放行后实测值冻结。观察员只读，调色师可登记但不能审核来源或签放生产。

新实体为 `RecipeRevision`（父子配方外键、来源快照、审核状态）与 `DyeBatch`（唯一缸号、批准试验外键、重量、Lab、色差、状态、签放人）。谱系为 `pending→approved`，生产为 `planned→hold/qualified→released`。生产扣留可重新测量；来源审核与生产签放均不重复执行。

新增接口：`GET/POST /revisions`、`POST /revisions/{id}/review`、`GET/POST /batches`、`PUT /batches/{id}/measurement`、`POST /batches/{id}/release`。五个后端业务文件位于 `backend/src/production_models.py`、`production_schemas.py`、`revision_service.py`、`batch_service.py`、`production_routes.py`；前端新页为 `pages/revisions.js` 和 `pages/batches.js`。

扩展 seed 新增 DY-PROD 冻结量产基准、PROD-REF/PROD-OK 两张实测染样、已批准量产试验和 DB-DEMO-001 待测缸次；全新库基础数据为3用户、4配方、62染样。连续seed只补缺项，保留人工编辑、修订谱系及缸次结果。本次没有更改旧表字段，自动建表为既有演示库补充两个新表；生产环境仍建议使用版本化迁移。

演示续篇：冻结原版→建立细支亚麻修订→主管审来源→调色师调整子版；从批准小样建立400kg生产缸→登记超色差实测并扣留→修色复测合格→主管签放。新的真实验收、4张1440×900截图与已知差异见 `test-artifacts/gb-1021/expansion/`。


## V3：染料称料、客户发样与色差补染

保留原配方、染样、PCA、复染签批、修订谱系和生产验收六页，新加三页，合计九个业务页面。

- **染料库存称料**：`DyeLot`按A/B/C组分记录唯一批号、可用kg、有效期和隔离状态。`DyeIssue`关联生产缸与实际来源批次，每缸每组分唯一，保留配方浓度快照和称料人。服务器计算“浓度%×生产kg÷100”，先锁缸次、按ID排序锁三个批次，全部校验后整单扣减。过期、隔离、不足或组分不匹配均不扣任一项；重复及并发领料只能成功一次。新生产签放必须A/B/C凭据齐全；历史已签放不追加领料或补扣。
- **客户色样签收**：`ColorDispatch`每个已签放缸只能发样一次，保存运单、客户、实测Lab、原目标、配方、生产kg和签放人快照。发样→实际收件人签收→接受或色差争议；未签收、跨缸结论和重复结论被拒绝。客户原争议记录冻结，后续补染另单处理。
- **色差客诉补染**：`ShadeComplaint`仅关联已签收且争议的发样单，申请kg不得超过原缸。主管裁定补染或驳回；补染须新的、未用于其他生产缸的approved trial，且新目标色与原客户目标ΔE≤3，系统按申请kg创建唯一关联新缸。新缸正常称料、实测、主管签放后，主管才可关闭；原缸、其他缸、未放行新缸或重复关闭都拒绝。

角色：调色师可入库、称料、发样、记录客户签收/反馈、提出客诉和建立已批准补染新缸；主管另外负责隔离/解除染料、补染裁定、生产签放及关闭客诉；观察员九页只读。客户反馈由内部岗位依据实际交接记录，不新增外部客户登录或对外消息。

接口：`GET/POST /dye-lots`、`PUT /dye-lots/{id}/state`、`GET/POST /dye-issues`；`GET/POST /color-dispatches`及`POST /{id}/receive`、`POST /{id}/conclusion`；`GET/POST /shade-complaints`及`POST /{id}/decision`、`POST /{id}/remake`、`POST /{id}/close`。主管专属动作由JWT后端依赖保护，非仅前端禁用。

新增代码按职责分为`fulfillment_models.py`、`fulfillment_schemas.py`、`fulfillment_routes.py`与`stock_service.py`、`dispatch_service.py`、`complaint_service.py`；前端新增`pages/stock.js`、`pages/dispatches.js`、`pages/complaints.js`。原batch_service在新建时保存配方快照、签放时核称料，补染新缸与客诉关联一次事务提交。四个新表自动补建，没有旧表列变更，保留既有released状态及旧格式目标快照。

Seed再补5个染料批次：A80kg、B40kg、C20kg可用，C隔离5kg、B已过期5kg作为拒领剧本；重复seed不补满消耗、不清除客诉、不覆盖人工修改。基础用户3、配方4、染样62仍保持；新签收与客诉从实际生产动作产生。

续篇剧本：为200kg靛蓝缸称A3.6/B0.8/C0.4kg→色差实测合格并签放→禾里服装收样，林工签收后记录标准光源色差争议→申请100kg补染→主管批准→新试验关联新缸，称A1.6/B0.4/C0.2kg→新缸正常实测签放→主管关闭客诉。新库存、客户与补染证据独立归档`test-artifacts/gb-1021/v3/`。

限制：库存仅染料批次扣料，不包含采购、货位、退库与盘点；客户运单和签收为本地人工凭据，未调用物流或客户门户。补染不出款、不改旧发样结论，不含合同索赔金额。Lab、光谱和工艺门限仍为模拟业务，需真实仪器及客户容差规范校准。


## V4：实测染样学习的补染浓度建议

保留既有九页，新增第十页「补染浓度建议」，业务数据持久化到 PostgreSQL。

- **学习与预测**：`shade_model.py` 纯计算模块。每个实测染样按其所属配方的三染料浓度归入同配方组；组内实测 Lab 取均值后，用标准化浓度对 L/a/b 做岭回归。给定目标色与 A/B/C 上限，在 0≤浓度≤上限的盒约束内搜索最小预测 ΔE 的浓度组合，并对离目标最近的实测组施加轻微先验，避免共线染料给出无依据的边界解。所有浓度四舍五入到四位小数，拒绝结果不携带浓度。
- **整组留出检验**：每次评估轮留一个完整配方组作检验，其余组训练，比较留出组合成的 Lab 与实测均值。少于 4 组、某染料浓度无变化、同组浓度不一致、留出最大 ΔE>3、目标色超出训练 Lab 范围、或上限内预测 ΔE>3 时，一律返回 `refused` 与中文原因；这些情形都不给浓度。
- **受理即固定依据**：`ShadeSuggestion`在受理时快照全部已测量染样（批号、配方、浓度、Lab）、组清单、目标色与三染料上限，并记录训练张数与组数。之后修改配方、追加染样或调整目标，都不改变本次快照；worker 只读取快照。关联色差客诉可选，受理时校验客诉存在。
- **排队、重试与不重复完成**：受理后写入 Redis `suggest:queue`，由现有 worker 消费。`state` 为 `queued→running→done/failed`。领取用条件 UPDATE 原子完成，重复队列消息只有一个能进入 `running`；发布结果同样以 `state='running'` 为条件，已完成结果不会被二次消息覆盖。`done` 不可重试；`failed` 可重试；`running` 超过 5 分钟后可重试（worker 崩溃残留），期间若有迟到的旧任务完成，发布保护会拒绝覆盖。入队失败会把记录标记为 `failed` 并返回 503，便于直接重试。
- **采纳为待审子版**：仅主管可把 `suggested` 结果采纳为冻结父配方的新子版。父配方必须已冻结且在该建议的训练组内。子版编号由 `{父编号}-S{建议号}` 推导，采纳记录 `ShadeSuggestionAdoption` 对建议、子版和修订均唯一；同时创建 `RecipeRevision`（`pending`，父快照内嵌目标、上限、预测色差与留出误差）。并发采纳或写入中断后重试都返回同一子版，不会产生第二条谱系；原配方保持冻结不变。子版仍须主管审来源、调色师调整、实测复染与主管签批，建议本身不签批。

接口：`GET/POST /shade-suggestions`、`POST /shade-suggestions/{id}/retry`、`POST /shade-suggestions/{id}/adopt`、`GET /shade-suggestion-adoptions`。受理与重试为调色师/主管，采纳为主管；观察员十页只读。

新增代码：`backend/src/suggestion_models.py`、`suggestion_schemas.py`、`suggestion_service.py`、`suggestion_routes.py`，纯模型 `shade_model.py`；前端新增`pages/suggestions.js`。`worker.py` 复用同一循环消费两个队列。两个新表自动补建，未改动旧表列。

页面可查看每条建议的预测色差、整组留出误差明细、拒绝原因、固定训练规模、排队/失败状态，以及采纳后的父配方与待审子版。seed 新增 7 个标定配方（各 3 张实测染样，浓度覆盖低到上限）；重复 seed 只补缺项，不覆盖人工修改、建议或采纳记录；基础用户 3、配方 11、染样 83。

演示剧本：受理目标 L48/a−2/b−25、上限 A2.8/B2.0/C1.8 → worker 整组留出最大 ΔE<1、给出约 A1.81/B0.41/C0.20 → 主管采纳为 DY-PROD 的待审子版 → 到配方修订谱系审来源、实测复染签批。把目标改成训练范围外（如 L95/a40/b40）或把上限压到 0.4%，可见两种拒绝原因。

限制：学习样本仍为演示 Lab，模型是三染料到 Lab 的线性近似，不含织物、温度、时间与染料相互作用；实际使用需以真实实测数据重新拟合并校准容差。建议仅供参考，不替代小样复染与人工签批。
