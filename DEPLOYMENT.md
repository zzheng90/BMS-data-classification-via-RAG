# CI/CD 学习手册 — BMS-RAG demo

从「本地改代码」到「自动部署到 AWS 上的 Kubernetes」的完整流水线。按阶段推进，每一步都能独立验证。

```
本地改代码 ─git push→ GitHub ─Actions→ 构建镜像 → 推送 GHCR
                                              │
                                        SSH 进 EC2
                                              │
                              k3s: kubectl apply / set image
                                              │
                     http://<EC2 公网 IP>:30080  ← 浏览器看到更新
```

---

## 仓库里各文件的作用

| 文件 | 属于哪一环 | 作用 |
|---|---|---|
| `Dockerfile` | Docker | 把应用打包成镜像；构建时预下载小模型，运行时离线、秒级启动 |
| `.dockerignore` | Docker | 缩小构建上下文，防止把 `.env`/私有数据打进镜像 |
| `Makefile` | 本地 | `make build/run/kind-load/redeploy` 等便捷命令 |
| `k8s/namespace.yaml` | Kubernetes | 独立命名空间 `bms-rag` |
| `k8s/configmap.yaml` | Kubernetes | 非机密配置（模型名、DashScope endpoint 等） |
| `k8s/secret.example.yaml` | Kubernetes | `DASHSCOPE_API_KEY` 的模板（真实值不进 git） |
| `k8s/deployment.yaml` | Kubernetes | Pod 规格、资源限制、健康探针、滚动更新策略 |
| `k8s/service.yaml` | Kubernetes | NodePort 30080，把 Pod 暴露到节点端口 |
| `k8s/kustomization.yaml` | Kubernetes | 聚合上面清单；CD 时用它替换镜像 tag |
| `.github/workflows/ci-cd.yml` | GitHub Actions | test → build-and-push → deploy 三个 job |
| `infra/*.tf` | AWS / IaC | Terraform：EC2 + 安全组 + 密钥对，一条命令建/拆 |
| `infra/userdata.sh` | AWS | 实例首次启动时装 k3s、加 swap |

---

## 阶段 0 — 本地准备（已完成的部分打勾）

- [x] 安装 `docker` / `kubectl` / `kind` / `gh` / `aws` / `terraform`
- [x] 启动 Docker Desktop
- [x] `git config --global user.name/email`
- [x] clone 仓库到 `~/Documents/CICD_test`
- [ ] **把 SSH 公钥加到 GitHub**（用于 `git push`）：
  1. 复制公钥：`cat ~/.ssh/id_ed25519.pub`
  2. GitHub → Settings → SSH and GPG keys → New SSH key → 粘贴 → 保存
  3. 验证：`ssh -T git@github.com` 应显示 `Hi zzheng90!`
- [ ] （可选，之后用）注册/登录 AWS，准备一个 IAM 用户

---

## 阶段 1 — 容器化，本地跑通

```bash
cd ~/Documents/CICD_test
make build           # docker build -t bms-rag:dev .
make run             # http://localhost:8501
```

打开浏览器访问 http://localhost:8501 ，应看到 “BMS-RAG Tool Demo” 界面。
没填 `DASHSCOPE_API_KEY` 时界面能开，点 Predict 会提示缺 key —— 正常。

**验证点**：`curl -fsS http://localhost:8501/_stcore/health` 返回 `ok`。

---

## 阶段 2 — 本地 Kubernetes（kind）

```bash
make kind-up                     # 建本地集群
make kind-load                   # 构建镜像并载入 kind
make deploy                      # kubectl apply -k k8s/
kubectl -n bms-rag get pods -w   # 等 Running + READY 1/1

# 注入真实 key（可选）
kubectl -n bms-rag create secret generic bms-rag-secrets \
  --from-literal=DASHSCOPE_API_KEY=sk-你的key --dry-run=client -o yaml | kubectl apply -f -
kubectl -n bms-rag rollout restart deployment/bms-rag

make forward                     # http://localhost:8501
```

**练习「改代码 → 看更新」循环**：

```bash
# 改 bms_rag_demo_app.py 里的 st.title(...) 文案
make redeploy                    # 重建 + 载入 + rollout restart
```

---

## 阶段 3 — GitHub Actions CI（build/push，无需 AWS）

1. 完成阶段 0 的 SSH key 步骤
2. 提交并推送：
   ```bash
   git add .
   git commit -m "Add Docker + k8s + CI/CD pipeline"
   git push origin main
   ```
3. GitHub → Actions 页，看 `ci-cd` 运行：`test` → `build-and-push` 变绿
4. 镜像出现在 GitHub → Packages：`ghcr.io/zzheng90/bms-data-classification-via-rag:latest`
   （首次为 private；到阶段 5 若让 EC2 免密拉取，需在 Package settings 改成 public）

`deploy` job 此时被 `vars.DEPLOY_ENABLED` 跳过 —— 阶段 5 再开。

---

## 阶段 4 — AWS 基础设施（Terraform）

### 4.1 准备 AWS 凭证
1. AWS Console → IAM → Users → Create user（如 `cicd-admin`）
2. 附加策略 `AdministratorAccess`（仅学习用；生产要收窄）
3. 该用户 → Security credentials → Create access key → CLI
4. 本地：
   ```bash
   aws configure          # 填 Access Key / Secret / region（如 eu-central-1）
   aws sts get-caller-identity   # 验证
   ```

### 4.2 建实例
```bash
cd infra
terraform init
terraform apply -var "my_ip=$(curl -s ifconfig.me)/32"
```
输出里记下 `public_ip` / `app_url` / `github_secrets`。

### 4.3 等 k3s 起来
```bash
ssh ec2-user@<public_ip>            # 首次约等 2-3 分钟
cat /var/log/bms-rag-bootstrap.done # 出现即就绪
kubectl get nodes                  # Ready
```

### 4.4 成本护栏
- AWS Console → Billing → Budgets → 建每月 $20 告警
- 学完立刻拆：`cd infra && terraform destroy`
- t3.small ≈ $0.021/小时 ≈ $15/月；EBS 20GB ≈ $1.6/月

---

## 阶段 5 — 打通完整 CD

### 5.1 GHCR 包设为 public
GitHub → 你的头像 → Packages → `bms-data-classification-via-rag` → Package settings → Change visibility → Public。
（这样 k3s 无需凭证即可 `docker pull`。）

### 5.2 GitHub 仓库加 Secrets / Variables
Settings → Secrets and variables → Actions：

| 类型 | 名字 | 值 |
|---|---|---|
| Variable | `DEPLOY_ENABLED` | `true` |
| Secret | `EC2_HOST` | terraform 输出的 `public_ip` |
| Secret | `EC2_USER` | `ec2-user` |
| Secret | `EC2_SSH_KEY` | `cat ~/.ssh/id_ed25519`（**私钥全文**） |
| Secret | `DASHSCOPE_API_KEY` | 你的 DashScope key（没有就填任意占位，Predict 会报错但部署仍成功） |

### 5.3 端到端测试
```bash
# 改一处显眼文案，如 st.title("BMS-RAG Tool Demo — v2")
git add -A && git commit -m "Bump title to v2" && git push
```
- GitHub Actions：`test` → `build-and-push` → `deploy` 全绿
- 浏览器打开 `http://<public_ip>:30080`，标题变成 v2 ✅
- 服务器上 `kubectl -n bms-rag rollout status deploy/bms-rag` 显示新版本

---

## 常见故障排查

| 现象 | 原因 / 处理 |
|---|---|
| Pod `OOMKilled` | t3.small 内存不够：`infra` 里改 `instance_type=t3.medium` 再 `terraform apply` |
| Pod `ImagePullBackOff` | GHCR 包还是 private → 改 public，或配 imagePullSecret |
| Actions `deploy` 报 SSH 失败 | `EC2_SSH_KEY` 要放**私钥**全文；安全组 22 端口只放行了你的 IP，Actions runner IP 不固定 → 见下 |
| Actions runner 连不上 EC2 | 把安全组 22 端口临时放开 `0.0.0.0/0`，或改用 AWS SSM / self-hosted runner（进阶） |
| 首次访问超时 | 模型加载 + 索引构建需时；`startupProbe` 给了 2.5 分钟，`kubectl logs` 观察 |
| `ssh -T git@github.com` 说 Permission denied | 公钥没加成功，或用了错的 key |

> ⚠️ 安全组 SSH 那条规则默认只放行你的公网 IP。GitHub Actions 的出口 IP 不固定，`deploy` job 可能连不上。
> 学习期最简单：把 `main.tf` 里 SSH 的 `cidr_blocks` 改成 `["0.0.0.0/0"]`（有暴力破解风险，密钥登录 + 学完即拆可接受）。
> 更正规：用 AWS SSM Session Manager 或在 EC2 上跑 self-hosted runner。

---

## 拆除（停止计费）

```bash
cd infra && terraform destroy -var "my_ip=$(curl -s ifconfig.me)/32"
kind delete cluster --name cicd-test
```
GHCR 镜像、GitHub 仓库不产生费用，可保留。
