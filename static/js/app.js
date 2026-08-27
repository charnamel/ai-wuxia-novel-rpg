        const output = document.getElementById('output');
        const input = document.getElementById('user_input');

        const append = (text, cls="") => {
            const div = document.createElement('div');
            div.className = cls;
            div.textContent = text;
            output.appendChild(div);
            output.scrollTop = output.scrollHeight;
        }

        // ===== NPC头像 / 武功图标 内联注入 =====
        function injectImages(html) {
            // 收集NPC名称 + 玩家姓名（按长度降序，避免短名匹配到长名的一部分）
            const npcNames = [...new Set(
                (npcList || []).map(n => n.name).filter(Boolean)
                .concat(playerName ? [playerName] : [])
            )].sort((a, b) => b.length - a.length);
            // 收集武功名称
            const skillNames = [...new Set((martialArts || []).map(a => a.name).filter(Boolean))]
                .sort((a, b) => b.length - a.length);

            // 注入NPC头像（搜索不到图片时自动隐藏，不显示裂图）
            for (const name of npcNames) {
                if (!name || name.length < 2) continue;
                const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const imgTag = `<img src="/static/images/npcs/${encodeURIComponent(name)}.png" onerror="this.style.display='none'" class="npc-avatar-inline" alt="${name}">`;
                html = html.replace(new RegExp(escaped, 'g'), `${imgTag}${name}`);
            }

            // 注入武功图标
            for (const name of skillNames) {
                if (!name || name.length < 2) continue;
                const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const imgTag = `<img src="/static/images/skills/${encodeURIComponent(name)}.png" onerror="this.style.display='none'" class="skill-icon-inline" alt="${name}">`;
                html = html.replace(new RegExp(escaped, 'g'), `${imgTag}${name}`);
            }

            return html;
        }
        async function send() {
            const msg = input.value.trim();
            if(!msg) return;
            input.value = '';
            await handleMessage(msg);
        }
        // ===== 任务系统 Web 函数 =====
        async function taskAction(action, name) {
            const cmd = `task_action|${action}|${name}`;
            await handleMessage(cmd);
        }

        async function createTask() {
            const nameInput = document.getElementById('new_task_name');
            const descInput = document.getElementById('new_task_desc');
            if (!nameInput || !descInput) {
                append("❌ 输入框未找到，请刷新面板", "change");
                return;
            }
            const name = nameInput.value.trim();
            const desc = descInput.value.trim();
            if(!name) {
                append("❌ 请输入任务名称", "change");
                return;
            }
            const cmd = `new_task|${name}|${desc}`;
            nameInput.value = '';
            descInput.value = '';
            await handleMessage(cmd);
        }

        async function updateTaskProgress(name) {
            const stage_input = document.getElementById(`stage_input_${name}`);
            const percent_input = document.getElementById(`percent_input_${name}`);
            const stage = stage_input ? stage_input.value.trim() : '';
            const percent_raw = percent_input ? percent_input.value.trim() : '';
            
            // 无论是否输入了进度，都构造命令，只发送 stage 和 percent（如果有）
            let cmd = `task_action|update_progress|${name}`;
            if (stage) cmd += `|${stage}`;
            // 如果输入了进度（且是有效数字），附加到命令
            if (percent_raw !== '') {
                const parsed = parseInt(percent_raw);
                if (!isNaN(parsed) && parsed >= 0 && parsed <= 100) {
                    cmd += `|${parsed}`;
                } else {
                    append("❌ 进度请输入 0-100 的数字", "change");
                    return;
                }
            }
            // 清空输入框
            if (stage_input) stage_input.value = '';
            if (percent_input) percent_input.value = '';
            await handleMessage(cmd);
        }
        async function sendCommand(cmd) {
            if(cmd === 'exit') {
                if(confirm("确定要退出吗？所有进度已自动保存，可随时重新打开网页。")) {
                    append("> " + cmd + " (断开连接)", "system");
                }
                return;
            }
            await handleMessage(cmd);
        }
        async function addNpcPrompt() {
            const name = prompt("NPC姓名：");
            if(!name) return;
            const identity = prompt("身份：") || "江湖人士";
            const fav = prompt("好感（-100~100）：") || "15";
            await handleMessage(`add_npc|${name}|${identity}|${fav}`);
        }
         window.onload = async function() {
            // 后台预加载NPC列表（供头像注入使用）
            try {
                const npcRes = await fetch('/npc/list');
                const npcData = await npcRes.json();
                if (npcData.status === 'success') {
                    npcList = npcData.npc_list || [];
                }
            } catch(e) {}
            // 后台预加载武功列表（供图标注入使用）
            try {
                const maRes = await fetch('/martial/list');
                const maData = await maRes.json();
                if (maData.status === 'success') {
                    martialArts = maData.arts || [];
                }
            } catch(e) {}
            // 后台预加载玩家姓名（供头像注入使用，头像与NPC同路径 /static/images/npcs/）
            try {
                const pRes = await fetch('/player/get');
                const pData = await pRes.json();
                if (pData.status === 'success' && pData.data && pData.data.name) {
                    playerName = pData.data.name;
                }
            } catch(e) {}

            try {
                const res = await fetch('/init');
                const data = await res.json();
                
                if(data.status === 'success') {
                    if(data.need_init) {
                        // 如果后端提示需要创建角色，隐藏所有聊天元素
                        document.getElementById('output').style.display = 'none';
                        document.getElementById('cmd-buttons').style.display = 'none';
                        document.getElementById('input-area').style.display = 'none';
                        document.getElementById('init-panel').style.display = 'block';
                    } else if(data.history) {
                        // 正常显示历史剧情
                        append(data.history, "plot");
                    }
                }
            } catch(e) {
                console.error("加载历史剧情失败，错误详情：", e);
                // 如果报错，至少让面板显示出来（兜底）
                document.getElementById('init-panel').style.display = 'block';
            }
        }
        async function handleMessage(msg, diceConfirm) {
            append("> " + msg, "system");
            // 用唯一 DOM 引用替代 querySelectorAll，防止并发时删错元素
            const loadingDiv = document.createElement('div');
            loadingDiv.className = "system";
            loadingDiv.textContent = "（正在推演...）";
            output.appendChild(loadingDiv);
            output.scrollTop = output.scrollHeight;
            try {
                const reqBody = {action: msg};
                if(diceConfirm !== undefined && diceConfirm !== null) {
                    reqBody.dice_confirm = diceConfirm;
                }
                const res = await fetch('/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(reqBody)
                });
                const data = await res.json();

                // 精确删除自己的 loading，不受其他并发请求干扰
                if (loadingDiv.parentNode) {
                    output.removeChild(loadingDiv);
                }

            // ===== 骰子待确认：显示掷骰确认面板 V4（武功品阶+境界） =====
            if(data.status === 'dice_pending') {
                const dc = data.dice_check;
                const diceDiv = document.createElement('div');
                diceDiv.className = "change";
                diceDiv.style.whiteSpace = "pre-wrap";
                diceDiv.style.border = "1px solid #ff0";
                diceDiv.style.padding = "10px";
                diceDiv.style.margin = "5px 0";
                diceDiv.style.borderRadius = "5px";
                let ampLine = '';
                if (dc.amplify_total && dc.amplify_total > 0) {
                    let ampParts = [];
                    if (dc.inner_name) ampParts.push(`内功${dc.inner_name}`);
                    if (dc.light_name) ampParts.push(`轻功${dc.light_name}`);
                    ampLine = `
增幅检定: ${ampParts.join('+')} → +${dc.amplify_total}`;
                } else if (dc.inner_name || dc.light_name) {
                    let ampParts = [];
                    if (dc.inner_name) ampParts.push(`内功${dc.inner_name}`);
                    if (dc.light_name) ampParts.push(`轻功${dc.light_name}`);
                    ampLine = `
增幅检定: ${ampParts.join('+')} → +0（增幅不足1）`;
                }
                diceDiv.innerHTML = `🎲 <b>武功检定确认</b>` +
                    `
武功: ${dc.skill_name}（${dc.skill_level}·品阶${dc.grade}级）` +
                    `
基础修正: +${dc.base_bonus}（整体境界）` +
                    `
武功加成: +${dc.skill_bonus}（品阶）+ ${dc.realm_bonus}（境界）= +${dc.skill_bonus + dc.realm_bonus}` +
                    ampLine +
                    `
总修正: +${dc.total_modifier}` +
                    `
DC: ${dc.dc}` + (dc.dc_reason ? ` (${dc.dc_reason})` : '') +
                    `
是否掷骰？`;
                output.appendChild(diceDiv);

                // 确认/跳过按钮
                const btnBox = document.createElement('div');
                btnBox.style.margin = "5px 0 10px 0";
                btnBox.style.display = "flex";
                btnBox.style.gap = "8px";

                const btnConfirm = document.createElement('button');
                btnConfirm.textContent = "🎲 确认掷骰";
                btnConfirm.className = 'cmd-btn';
                btnConfirm.style.background = '#4f4';
                btnConfirm.style.color = '#000';
                btnConfirm.onclick = function() {
                    btnBox.style.display = 'none';
                    diceDiv.style.opacity = '0.5';
                    handleMessage(msg, true);
                };
                btnBox.appendChild(btnConfirm);

                const btnSkip = document.createElement('button');
                btnSkip.textContent = "⏭️ 跳过检定";
                btnSkip.className = 'cmd-btn';
                btnSkip.style.background = '#888';
                btnSkip.style.color = '#fff';
                btnSkip.onclick = function() {
                    btnBox.style.display = 'none';
                    diceDiv.style.opacity = '0.5';
                    handleMessage(msg, false);
                };
                btnBox.appendChild(btnSkip);

                output.appendChild(btnBox);
                output.scrollTop = output.scrollHeight;
                return;
            }

            if(data.status === 'success') {
                // ===== 新增：任务面板特殊处理 =====
                if(data.status === 'success') {
                // ===== 任务面板：追加内容，不清空上下文 =====
                    if(data.is_task_panel) {
                        // 1. 显示任务列表纯文本（用 pre 保留换行格式）
                        const pre = document.createElement('pre');
                        pre.className = "plot";
                        pre.style.whiteSpace = 'pre-wrap';
                        pre.textContent = data.plot;
                        output.appendChild(pre);
                        output.scrollTop = output.scrollHeight;

                        // 2. 创建按钮容器（始终存在，用于放置任务操作按钮和新建按钮）
                        const btnContainer = document.createElement('div');
                        btnContainer.style.marginTop = '5px';
                        btnContainer.style.marginBottom = '10px';
                        btnContainer.style.paddingLeft = '10px';

                        if(data.tasks && data.tasks.length > 0) {
                            data.tasks.forEach(task => {
                                const group = document.createElement('div');
                                group.style.marginTop = '3px';
                                group.style.display = 'flex';
                                group.style.flexWrap = 'wrap';
                                group.style.gap = '4px';
                                group.style.alignItems = 'center';

                                const label = document.createElement('span');
                                label.textContent = `#${task.id} ${task.display_name}：`;
                                label.style.color = '#4f4';
                                label.style.fontSize = '12px';
                                label.style.marginRight = '4px';
                                group.appendChild(label);

                                if(task.status === 'completed') {
                                    // ★ 已完成任务：只显示删除按钮
                                    const btnDelete = document.createElement('button');
                                    btnDelete.textContent = '🗑️删除';
                                    btnDelete.className = 'cmd-btn';
                                    btnDelete.style.background = '#f44';
                                    btnDelete.style.color = '#fff';
                                    btnDelete.onclick = function() {
                                        if(confirm(`确定删除任务 ${task.id} 吗？`)) {
                                            sendCommand(`task_action|delete|${task.id}`);
                                        }
                                    };
                                    group.appendChild(btnDelete);
                                } else {
                                    // ★ 未完成任务：显示所有操作按钮
                                    // 完成按钮
                                    const btnComplete = document.createElement('button');
                                    btnComplete.textContent = '✅完成';
                                    btnComplete.className = 'cmd-btn';
                                    btnComplete.style.background = '#4f4';
                                    btnComplete.style.color = '#000';
                                    btnComplete.onclick = function() {
                                        sendCommand(`task_action|complete|${task.id}`);
                                    };
                                    group.appendChild(btnComplete);

                                    // 删除按钮
                                    const btnDelete = document.createElement('button');
                                    btnDelete.textContent = '🗑️删除';
                                    btnDelete.className = 'cmd-btn';
                                    btnDelete.style.background = '#f44';
                                    btnDelete.style.color = '#fff';
                                    btnDelete.onclick = function() {
                                        if(confirm(`确定删除任务 ${task.id} 吗？`)) {
                                            sendCommand(`task_action|delete|${task.id}`);
                                        }
                                    };
                                    group.appendChild(btnDelete);

                                    // 搁置/激活按钮
                                    const btnSuspend = document.createElement('button');
                                    btnSuspend.textContent = task.suspended ? '▶️激活' : '⏸️搁置';
                                    btnSuspend.className = 'cmd-btn';
                                    btnSuspend.style.background = task.suspended ? '#4ff' : '#ff4';
                                    btnSuspend.style.color = '#000';
                                    btnSuspend.onclick = function() {
                                        sendCommand(`task_action|toggle_suspend|${task.id}`);
                                    };
                                    group.appendChild(btnSuspend);

                                    // 切换类型按钮
                                    const btnType = document.createElement('button');
                                    btnType.textContent = task.type === 'main' ? '🔄转支线' : '🔄转主线';
                                    btnType.className = 'cmd-btn';
                                    btnType.style.background = '#44f';
                                    btnType.style.color = '#fff';
                                    btnType.onclick = function() {
                                        sendCommand(`task_action|toggle_type|${task.id}`);
                                    };
                                    group.appendChild(btnType);

                                    // 更新进度按钮
                                    const btnUpdate = document.createElement('button');
                                    btnUpdate.textContent = '📤更新';
                                    btnUpdate.className = 'cmd-btn';
                                    btnUpdate.style.background = '#4ff';
                                    btnUpdate.style.color = '#000';
                                    btnUpdate.onclick = function() {
                                        const stage = prompt('请输入当前阶段描述：', task.stage || '');
                                        if(stage === null) return;
                                        const percent = prompt('请输入进度百分比（0-100）：', task.progress || 0);
                                        if(percent === null) return;
                                        const p = parseInt(percent);
                                        if(isNaN(p) || p < 0 || p > 100) {
                                            alert('请输入0-100的数字');
                                            return;
                                        }
                                        let cmd = `task_action|update_progress|${task.id}`;
                                        if(stage) cmd += `|${stage}`;
                                        cmd += `|${p}`;
                                        sendCommand(cmd);
                                    };
                                    group.appendChild(btnUpdate);
                                }

                                btnContainer.appendChild(group);
                            });
                        }

                        // ★ 新建任务按钮：始终显示，放在所有任务按钮后面
                        const newBtn = document.createElement('button');
                        newBtn.textContent = '➕ 新建任务';
                        newBtn.className = 'cmd-btn';
                        newBtn.style.background = '#4f4';
                        newBtn.style.color = '#000';
                        newBtn.style.marginTop = '8px';
                        newBtn.onclick = function() {
                            const name = prompt('请输入任务名称：');
                            if(!name) return;
                            const desc = prompt('请输入任务描述：');
                            if(!desc) return;
                            sendCommand(`new_task|${name}|${desc}`);
                        };
                        btnContainer.appendChild(newBtn);

                        output.appendChild(btnContainer);
                        output.scrollTop = output.scrollHeight;
                        return; // 任务面板处理完毕
                    }

                    
                    // ===== 普通剧情/命令显示（追加内容） =====
                    if(data.round) {
                        const roundDiv = document.createElement('div');
                        roundDiv.className = "system";
                        roundDiv.textContent = `[第${data.round}轮]`;
                        output.appendChild(roundDiv);
                    }
                    // ===== 骰子检定结果显示 V4（武功品阶+8档分级） =====
                    if(data.dice_result) {
                        const dr = data.dice_result;
                        const diceResultDiv = document.createElement('div');
                        diceResultDiv.className = "change";
                        diceResultDiv.style.whiteSpace = "pre-wrap";
                        diceResultDiv.style.border = "1px solid #0ff";
                        diceResultDiv.style.padding = "8px";
                        diceResultDiv.style.margin = "5px 0";
                        diceResultDiv.style.borderRadius = "5px";
                        // 根据8档分级设置颜色和图标
                        let verdictColor = '#fff';
                        let verdictIcon = '🎲';
                        const vg = dr.verdict_grade;
                        if(vg === 1) { verdictColor = '#ff0'; verdictIcon = '🌟'; }      // 完美碾压
                        else if(vg === 2) { verdictColor = '#ff0'; verdictIcon = '✨'; } // 超常发挥
                        else if(vg === 3) { verdictColor = '#4f4'; verdictIcon = '✅'; } // 正常发挥
                        else if(vg === 4) { verdictColor = '#8f8'; verdictIcon = '⚡'; } // 差强人意
                        else if(vg === 5) { verdictColor = '#fc8'; verdictIcon = '⚠️'; } // 功亏一篑
                        else if(vg === 6) { verdictColor = '#f88'; verdictIcon = '❌'; } // 拙于应对
                        else if(vg === 7) { verdictColor = '#f44'; verdictIcon = '💥'; } // 力屈受挫
                        else if(vg === 8) { verdictColor = '#f00'; verdictIcon = '💀'; } // 惨败而归

                        const rollsStr = dr.dice_rolls ? dr.dice_rolls.join(', ') : dr.dice_natural;
                        let effectLines = '';
                        // 优先用 effect_results（包含主武功+内功+轻功全部特效）
                        const effectList = (dr.effect_results && dr.effect_results.length) ? dr.effect_results : (dr.effect_result ? [dr.effect_result] : []);
                        if (effectList.length > 0) {
                            effectLines = effectList.map(er => {
                                if (!er) return '';
                                const triggeredIcon = er.triggered ? '⚡' : '○';
                                const triggeredText = er.triggered ? '已触发' : '未触发';
                                const triggeredColor = er.triggered ? '#fa8' : '#888';
                                const role = er.skill_name === dr.skill_name ? '主武功' : '增幅源';
                                const hintLine = (er.triggered && er.narrative_hint) ? `\n<span style="color:#fd6">${er.narrative_hint}</span>` : '';
                                return `
<span style="color:${triggeredColor}">${triggeredIcon} 特效[${role}·${er.skill_name}]·${er.effect_name}（${er.effect_category}类）→ 触发率 ${er.final_rate}% · ${triggeredText}</span>${hintLine}`;
                            }).join('');
                        }
                        diceResultDiv.innerHTML = `${verdictIcon} <b style="color:${verdictColor}">【${dr.verdict}】</b> 第${vg}档` +
                            `
武功: ${dr.skill_name}（${dr.skill_level}·品阶${dr.grade}级）` +
                            `
基础修正: +${dr.base_bonus} | 武功加成: +${dr.skill_bonus}+${dr.realm_bonus}=+${dr.skill_bonus + dr.realm_bonus} | 总修正: +${dr.total_modifier}` +
                            `
DC: ${dr.dc}` + (dr.dc_reason ? ` (${dr.dc_reason})` : '') +
                            `
🎲 d20: [${rollsStr}] + ${dr.total_modifier} = ${dr.dice_total} vs DC ${dr.dc} → 差值 ${dr.delta >= 0 ? '+' : ''}${dr.delta}` +
                            effectLines;
                        output.appendChild(diceResultDiv);
                        output.scrollTop = output.scrollHeight;
                    }
                    if(data.plot) {
                        const div = document.createElement('div');
                        div.className = "plot";
                        div.innerHTML = injectImages(data.plot);
                        output.appendChild(div);
                        output.scrollTop = output.scrollHeight;
                    }
                    
                    // 状态信息展示（NPC/道具/地点/时间/天气）
                    if(data.npc_change && data.npc_change !== "无活跃NPC") {
                        const npcDiv = document.createElement('div');
                        npcDiv.className = "change";
                        npcDiv.style.whiteSpace = "pre-wrap";
                        npcDiv.textContent = "【NPC】\n" + data.npc_change;
                        output.appendChild(npcDiv);
                    }
                    if(data.npc_memory) {
                        const memDiv = document.createElement('div');
                        memDiv.className = "change";
                        memDiv.style.whiteSpace = "pre-wrap";
                        memDiv.textContent = "【NPC记忆】\n" + data.npc_memory;
                        output.appendChild(memDiv);
                    }
                    if(data.item_status && data.item_status !== "无变化") {
                        const itemDiv = document.createElement('div');
                        itemDiv.className = "change";
                        itemDiv.style.whiteSpace = "pre-wrap";
                        itemDiv.textContent = "【状态】\n" + data.item_status;
                        output.appendChild(itemDiv);
                    }
                    if(data.location) {
                        append(data.location, "change");
                    }
                    if(data.task_status) {
                        const taskDiv = document.createElement('div');
                        taskDiv.className = "change";
                        taskDiv.style.whiteSpace = "pre-wrap";
                        taskDiv.textContent = "【任务】\n" + data.task_status;
                        output.appendChild(taskDiv);
                    }
                    if(data.action_options) {
                        const optDiv = document.createElement('div');
                        optDiv.className = "change";
                        optDiv.style.whiteSpace = "pre-wrap";
                        optDiv.textContent = "【行动选项】\n" + data.action_options;
                        output.appendChild(optDiv);
                    }
                    
                    if(data.battle_action === "require_input") {
                        append("【系统】回合继续！请在下方的输入框中输入本回合的出招/打斗动作。", "system");
                        input.placeholder = "⚔️ 战斗中，输入招式...";
                        input.focus();
                    }

                    if (data.battle_action !== "require_input") {
                        input.placeholder = "输入你的行动...";
                    }
                    
                    if (data.reload) {
                        setTimeout(() => {
                            location.reload();
                        }, 2000);
                    }
                } else {
                    append("【系统错误】" + data.message, "change");
                }
            }
        } catch(e) {
                append("【网络错误】" + e, "change");
            }
        }
                // 🆕 新增：提交创建角色的函数
        async function submitCreatePlayer() {
            const name = document.getElementById('init_name').value.trim();
            const origin = document.getElementById('init_origin').value.trim();
            const ability = document.getElementById('init_ability').value.trim();
            
            if(!name || !origin || !ability) {
                alert("请完整填写姓名、身世和功法！");
                return;
            }
            
            append("正在创建角色「" + name + "」...", "system");
            try {
                const res = await fetch('/create_player', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: name, origin: origin, ability: ability})
                });
                const data = await res.json();
                if(data.status === 'success') {
                    append("✅ 角色创建成功！即将进入江湖...", "system");
                    setTimeout(() => {
                        location.reload(); // 刷新页面，重新调用 /init
                    }, 1500);
                } else {
                    append("【系统错误】" + data.message, "change");
                }
            } catch(e) {
                append("【网络错误】" + e, "change");
            }
        }

        // ===== 世界书状态管理 =====
        async function updateWorldbookStatus() {
            try {
                const res = await fetch('/worldbook/status');
                const data = await res.json();
                const icon = document.getElementById('worldbook-status-icon');
                const text = document.getElementById('worldbook-status-text');
                const detail = document.getElementById('worldbook-status-detail');
                if (data.status === 'ready') {
                    icon.textContent = '✅';
                    icon.style.color = '#4c4';
                    text.textContent = '世界书检索已就绪';
                    text.style.color = '#4c4';
                    // 语义检索状态
                    let semText = '';
                    if (data.semantic) {
                        if (data.semantic.available) {
                            semText = ` | 语义✅ ${data.semantic.vector_count}条向量`;
                        } else if (data.semantic.enabled) {
                            semText = (data.semantic.model_ready && !data.semantic.vector_count)
                                ? ' | 语义⚠️无向量缓存(点重建)'
                                : ' | 语义⏳加载中';
                        } else {
                            semText = ' | 语义未启用';
                        }
                    }
                    detail.textContent = `${data.total_entries}条 / ${data.total_keywords}关键词${semText} / 构建于 ${data.last_build_time || ''}`;
                    detail.style.color = '#888';
                } else {
                    icon.textContent = '⚠️';
                    icon.style.color = '#ec4';
                    text.textContent = '世界书检索未初始化';
                    text.style.color = '#ec4';
                    detail.textContent = '请检查数据文件';
                    detail.style.color = '#888';
                }
            } catch(e) {
                // 静默失败（世界书不可用时不影响主功能）
            }
        }

        async function worldbookRebuild() {
            try {
                append('🔄 正在重建索引（含语义向量编码，约30秒）...', 'system');
                const res = await fetch('/worldbook/rebuild', {method: 'POST'});
                const data = await res.json();
                if (data.success) {
                    let semInfo = '';
                    if (data.semantic && data.semantic.available) {
                        semInfo = `，语义检索✅ ${data.semantic.vector_count}条向量`;
                    } else if (data.semantic && data.semantic.enabled) {
                        semInfo = '，语义检索⏳加载中';
                    }
                    append(`✅ 世界书索引已重建：${data.total_entries}条条目${semInfo}`, 'system');
                } else {
                    append(`⚠️ 重建失败：${data.message || '未知错误'}`, 'change');
                }
                updateWorldbookStatus();
            } catch(e) {
                append('【网络错误】无法重建世界书（可能向量编码超时，请稍后重试）', 'change');
            }
        }

        // ===== 长期记忆状态管理 =====
        async function updateMemoryStatus() {
            try {
                const res = await fetch('/memory/status');
                const data = await res.json();
                const icon = document.getElementById('memory-status-icon');
                const text = document.getElementById('memory-status-text');
                const detail = document.getElementById('memory-status-detail');
                if (!icon || !text) return;
                if (data.backend === 'cloud') {
                    icon.textContent = '☁️';
                    icon.style.color = '#59c';
                    text.textContent = '长期记忆 · 云端模式';
                    text.style.color = '#59c';
                    detail.textContent = '百炼云向量库';
                    detail.style.color = '#888';
                    return;
                }
                let catText = '';
                if (data.categories) {
                    const parts = Object.entries(data.categories)
                        .sort((a, b) => b[1] - a[1])
                        .slice(0, 4)
                        .map(([k, v]) => `${k}${v}`);
                    if (parts.length) catText = `（${parts.join('/')}）`;
                }
                if (data.status === 'ready') {
                    icon.textContent = '✅';
                    icon.style.color = '#4c4';
                    text.textContent = '长期记忆已就绪';
                    text.style.color = '#4c4';
                    detail.textContent = `${data.total_entries}条${catText} · ${data.model || ''}`;
                } else if (data.status === 'loading') {
                    icon.textContent = '⏳';
                    icon.style.color = '#ec4';
                    text.textContent = '本地记忆模型加载中';
                    text.style.color = '#ec4';
                    detail.textContent = `${data.total_entries}条 · ${data.model || ''}`;
                } else {
                    icon.textContent = '⚠️';
                    icon.style.color = '#ec4';
                    text.textContent = '本地记忆不可用';
                    text.style.color = '#ec4';
                    detail.textContent = data.model_error ? String(data.model_error).slice(0, 60) : '请检查依赖安装';
                }
                detail.style.color = '#888';
            } catch(e) {
                // 静默失败（记忆库不可用时不影响主功能）
            }
        }
        async function memoryRebuild() {
            try {
                append('🔄 正在重建本地记忆向量（后台全量重编码，约1-2分钟，不影响游戏进行）...', 'system');
                const res = await fetch('/memory/rebuild', {method: 'POST'});
                const data = await res.json();
                if (!data.success) {
                    append(`⚠️ 重建失败：${data.message || '未知错误'}`, 'change');
                    return;
                }
                append(`✅ ${data.message || '重建已开始'}`, 'system');
                // 后台重建期间每10秒刷新一次状态，最长等5分钟
                let tries = 0;
                const poll = setInterval(async () => {
                    tries++;
                    await updateMemoryStatus();
                    const text = document.getElementById('memory-status-text');
                    if ((text && text.textContent.includes('已就绪')) || tries >= 30) {
                        clearInterval(poll);
                        if (text && text.textContent.includes('已就绪')) {
                            append('✅ 本地记忆向量重建完成，状态栏已更新', 'system');
                        }
                    }
                }, 10000);
            } catch(e) {
                append('【网络错误】无法重建本地记忆（请稍后重试）', 'change');
            }
        }

        // 页面加载后立即检查一次，然后每30秒刷新
        updateWorldbookStatus();
        setInterval(updateWorldbookStatus, 30000);
        updateMemoryStatus();
        setInterval(updateMemoryStatus, 30000);
    

        function openPlayerEditor() {
            document.getElementById('editor-modal').style.display = 'block';
            loadPlayerRaw();
        }
        function closeEditor() {
            document.getElementById('editor-modal').style.display = 'none';
        }
        async function loadPlayerRaw() {
            try {
                const res = await fetch('/player/get');
                const data = await res.json();
                if(data.status === 'success') {
                    document.getElementById('player_json_editor').value = JSON.stringify(data.data, null, 2);
                } else {
                    alert('读取失败：' + data.message);
                }
            } catch(e) {
                alert('网络错误：' + e);
            }
        }

        // ======= 装备管理器 JavaScript =======
        let equipmentData = null;
        // 缓存可装备项名称（按slot），用index调用避免转义问题
        let equipmentNameCache = {};

        function toggleEquipmentPanel() {
            const modal = document.getElementById('equipment-modal');
            if (modal.style.display === 'none' || !modal.style.display) {
                modal.style.display = 'block';
                loadEquipment();
            } else {
                modal.style.display = 'none';
            }
        }

        async function loadEquipment() {
            const body = document.getElementById('equipment-body');
            body.innerHTML = '<p style="color:#888; font-size:12px; text-align:center;">加载中...</p>';
            try {
                const res = await fetch('/player/equipped');
                const data = await res.json();
                if (data.status === 'success') {
                    equipmentData = data;
                    renderEquipment();
                } else {
                    body.innerHTML = '<p style="color:#a44;">加载失败：' + escapeHtml(data.message || '') + '</p>';
                }
            } catch(e) {
                body.innerHTML = '<p style="color:#a44;">网络错误：' + escapeHtml(String(e)) + '</p>';
            }
        }

        function renderEquipment() {
            if (!equipmentData) return;
            const body = document.getElementById('equipment-body');
            const equipped = equipmentData.equipped || {};
            const available = equipmentData.available || {};

            // 槽位配置
            const slotConfig = [
                {key: 'inner_martial', label: '内功', color: '#8af', desc: '影响骰子加成', isList: false},
                {key: 'light_martial', label: '轻功', color: '#8fa', desc: '影响骰子加成', isList: false},
                {key: 'weapon', label: '武器', color: '#fa8', desc: '仅作AI提示词参考，不影响数值', isList: false},
                {key: 'armor', label: '防具', color: '#a8f', desc: '仅作AI提示词参考，不影响数值', isList: false},
                {key: 'items', label: '随身物品', color: '#fc8', desc: '携带在身上的物品，可多个', isList: true},
            ];

            let html = '';
            slotConfig.forEach(slot => {
                const isList = slot.isList;
                const current = equipped[slot.key];
                const currentList = isList ? (Array.isArray(current) ? current : []) : null;
                const currentSingle = isList ? null : (current || '');
                const items = available[slot.key] || [];
                const isMartial = slot.key.includes('martial');

                // 缓存名称列表
                equipmentNameCache[slot.key] = items.map(it => isMartial ? it.name : it);

                html += '<div style="margin-bottom:18px; background:#111; border:1px solid #234; border-radius:6px; padding:12px;">';
                // 标题行
                html += '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">';
                html += '<div style="color:' + slot.color + '; font-size:14px; font-weight:bold;">' + slot.label + '</div>';
                html += '<div style="font-size:11px; color:#666;">' + slot.desc + '</div>';
                html += '</div>';
                // 当前装备
                html += '<div style="margin-bottom:10px; padding:8px; background:#0a1a2a; border:1px solid #345; border-radius:4px;">';
                if (isList) {
                    if (currentList.length > 0) {
                        html += '<div style="color:#4f4; margin-bottom:4px;">✓ 已携带 (' + currentList.length + '件)：</div>';
                        currentList.forEach(itemName => {
                            const itemIdx = equipmentNameCache[slot.key].indexOf(itemName);
                            html += '<div style="display:flex; justify-content:space-between; align-items:center; padding:3px 6px; margin:2px 0; background:#1a2a1a; border:1px solid #3c3; border-radius:3px;">';
                            html += '<span style="color:#4f4; font-size:12px;">' + escapeHtml(itemName) + '</span>';
                            html += '<button onclick="unequipListItem(\'' + slot.key + '\', ' + itemIdx + ')" class="cmd-btn" style="background:#555; color:#ddd; font-size:10px; padding:1px 6px;">取下</button>';
                            html += '</div>';
                        });
                    } else {
                        html += '<span style="color:#666;">未携带</span>';
                    }
                } else {
                    if (currentSingle) {
                        html += '<span style="color:#4f4;">✓ 当前装备：' + escapeHtml(currentSingle) + '</span> ';
                        html += '<button onclick="unequipItem(\'' + slot.key + '\')" class="cmd-btn" style="background:#555; color:#ddd; font-size:11px; padding:2px 8px;">卸下</button>';
                    } else {
                        html += '<span style="color:#666;">未装备</span>';
                    }
                }
                html += '</div>';
                // 可装备列表
                if (items.length === 0) {
                    html += '<div style="color:#555; font-size:12px; padding:5px;">无可装备项</div>';
                } else {
                    html += '<div style="display:flex; flex-direction:column; gap:4px;">';
                    items.forEach((item, idx) => {
                        const name = isMartial ? item.name : item;
                        const exp = isMartial ? item.exp : null;
                        const isEquipped = isList
                            ? (currentList.includes(name))
                            : (currentSingle === name);
                        html += '<div style="display:flex; justify-content:space-between; align-items:center; padding:6px 8px; ';
                        html += 'background:' + (isEquipped ? '#1a2a1a' : '#1a1a2a') + '; ';
                        html += 'border:1px solid ' + (isEquipped ? '#4c4' : '#334') + '; border-radius:4px;">';
                        html += '<span style="color:' + (isEquipped ? '#4f4' : '#ccc') + '; font-size:12px;">' + escapeHtml(name);
                        if (exp !== null && exp !== undefined) {
                            html += ' <span style="color:#668; font-size:10px;">(修为' + exp + ')</span>';
                        }
                        html += '</span>';
                        if (isEquipped) {
                            html += '<span style="color:#4c4; font-size:11px;">已携带 ✓</span>';
                        } else {
                            html += '<button onclick="equipItem(\'' + slot.key + '\', ' + idx + ')" class="cmd-btn" style="background:#248; color:#fff; font-size:11px; padding:2px 10px;">携带</button>';
                        }
                        html += '</div>';
                    });
                    html += '</div>';
                }
                html += '</div>';
            });

            body.innerHTML = html;
        }

        async function equipItem(slot, index) {
            const name = (equipmentNameCache[slot] || [])[index];
            if (!name) {
                alert('参数错误：未找到装备项');
                return;
            }
            try {
                const res = await fetch('/player/equip', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({slot: slot, name: name})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    if (data.plot) append(data.plot, 'system');
                    loadEquipment();
                } else {
                    alert('装备失败：' + (data.message || '未知错误'));
                }
            } catch(e) {
                alert('网络错误：' + e);
            }
        }

        async function unequipItem(slot) {
            try {
                const res = await fetch('/player/unequip', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({slot: slot})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    if (data.plot) append(data.plot, 'system');
                    loadEquipment();
                } else {
                    alert('卸下失败：' + (data.message || '未知错误'));
                }
            } catch(e) {
                alert('网络错误：' + e);
            }
        }

        async function unequipListItem(slot, index) {
            const name = (equipmentNameCache[slot] || [])[index];
            if (!name) {
                alert('参数错误：未找到物品');
                return;
            }
            try {
                const res = await fetch('/player/unequip', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({slot: slot, name: name})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    if (data.plot) append(data.plot, 'system');
                    loadEquipment();
                } else {
                    alert('取下失败：' + (data.message || '未知错误'));
                }
            } catch(e) {
                alert('网络错误：' + e);
            }
        }
        async function savePlayerRaw() {
            if(!confirm('确定要覆盖保存吗？改错可能导致存档损坏！')) return;
            try {
                const raw = document.getElementById('player_json_editor').value;
                const player_data = JSON.parse(raw);
                const res = await fetch('/player/save_raw', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({player_data: player_data})
                });
                const data = await res.json();
                alert(data.message);
                if(data.status === 'success') {
                    closeEditor();
                }
            } catch(e) {
                alert('保存失败：' + e);
            }
        }
        // ======= 地图系统 JavaScript =======
        let currentMapParent1 = '';  // 当前选中的一级区域ID
        let currentMapParent2 = '';  // 当前选中的二级城市ID
        let currentMapTarget = null; // 当前目标地点
        let mapDataCache = null;
        let currentLocation = '';    // 玩家当前所在位置名称
        let mapRefreshTimer = null; // 定时刷新定时器

        function toggleMapPanel() {
            const panel = document.getElementById('map-panel');
            if (panel.style.display === 'none' || !panel.style.display) {
                panel.style.display = 'block';
                loadMapData();
                // 启动定时刷新（每15秒刷新一次当前位置）
                if (mapRefreshTimer) clearInterval(mapRefreshTimer);
                mapRefreshTimer = setInterval(() => {
                    if (panel.style.display !== 'none') {
                        loadMapData();
                    }
                }, 15000);
            } else {
                panel.style.display = 'none';
                // 停止定时刷新
                if (mapRefreshTimer) {
                    clearInterval(mapRefreshTimer);
                    mapRefreshTimer = null;
                }
            }
        }

        async function loadMapData() {
            try {
                const res = await fetch('/map/get');
                const data = await res.json();
                if (data.status === 'success') {
                    mapDataCache = data.data;
                    currentMapTarget = data.target || null;
                    currentLocation = data.current_location || '';
                    renderMapLevel1();
                    renderMapLevel2();
                    renderMapLevel3();
                    updateMapTargetDisplay();
                }
            } catch(e) {
                console.error('加载地图失败:', e);
            }
        }

        function updateMapTargetDisplay() {
            // 更新当前位置显示
            const locDisplay = document.getElementById('map-current-location');
            if (currentLocation) {
                locDisplay.textContent = '📍 当前：' + currentLocation;
                locDisplay.style.color = '#4f8';
            } else {
                locDisplay.textContent = '📍 当前：未定位';
                locDisplay.style.color = '#888';
            }
            // 更新目标位置显示
            const display = document.getElementById('map-target-display');
            if (currentMapTarget && currentMapTarget.full_path) {
                display.textContent = '🎯 目标：' + currentMapTarget.full_path;
                display.style.color = '#ff4';
            } else {
                display.textContent = '🎯 目标：未设置';
                display.style.color = '#888';
            }
        }

        function renderMapLevel1() {
            const container = document.getElementById('map-level1');
            const regions = mapDataCache.regions || [];
            if (regions.length === 0) {
                container.innerHTML = '<span style="color:#666;">暂无区域</span>';
                return;
            }
            let html = '';
            regions.forEach(r => {
                const isSelected = r.id === currentMapParent1;
                const isTarget = currentMapTarget && currentMapTarget.id === r.id;
                // 检查是否是当前位置（包含匹配）
                const isHere = currentLocation && (currentLocation.includes(r.name) || r.name.includes(currentLocation));
                const bgColor = isTarget ? '#442' : (isHere ? '#311' : (isSelected ? '#224' : 'transparent'));
                const textColor = isTarget ? '#ff4' : (isHere ? '#4f8' : (isSelected ? '#4ff' : '#aaa'));
                html += `<div style="padding:4px 6px; margin:2px 0; border-radius:4px; cursor:pointer; display:flex; justify-content:space-between; align-items:center; background:${bgColor};" onclick="handleLevel1Click('${r.id}')">
                    <span style="color:${textColor};">${isHere ? '📍' : (isTarget ? '🎯 ' : '')}${r.name}</span>
                    <div>
                        <button class="cmd-btn" style="padding:1px 6px; font-size:10px; background:#226; margin-right:3px;" onclick="event.stopPropagation(); renameMapNode('${r.id}', '${r.name}')">✏️</button>
                        <button class="cmd-btn" style="padding:1px 6px; font-size:10px; background:#a22;" onclick="event.stopPropagation(); deleteMapNode('${r.id}')">🗑️</button>
                    </div>
                </div>`;
            });
            container.innerHTML = html;
        }

        function handleLevel1Click(id) {
            const region = (mapDataCache.regions || []).find(r => r.id === id);
            if (!region) return;
            const wasSelected = id === currentMapParent1;
            selectMapLevel1(id);
            // 如果点击的是已选中的，设为目标
            if (wasSelected) {
                setMapTarget(1, id, region.name, '', '');
            }
        }

        function selectMapLevel1(id) {
            currentMapParent1 = id;
            currentMapParent2 = '';
            renderMapLevel1();
            renderMapLevel2();
            renderMapLevel3();
            document.getElementById('add-level2-btn').disabled = false;
            document.getElementById('add-level3-btn').disabled = true;
        }

        function renderMapLevel2() {
            const container = document.getElementById('map-level2');
            if (!currentMapParent1) {
                container.innerHTML = '<span style="color:#666;">请先选择区域</span>';
                return;
            }
            const region = (mapDataCache.regions || []).find(r => r.id === currentMapParent1);
            if (!region || !region.children || region.children.length === 0) {
                container.innerHTML = '<span style="color:#666;">暂无城市</span>';
                return;
            }
            let html = '';
            region.children.forEach(c => {
                const isSelected = c.id === currentMapParent2;
                const isTarget = currentMapTarget && currentMapTarget.id === c.id;
                const isHere = currentLocation && (currentLocation.includes(c.name) || c.name.includes(currentLocation));
                const bgColor = isTarget ? '#442' : (isHere ? '#311' : (isSelected ? '#131' : 'transparent'));
                const textColor = isTarget ? '#ff4' : (isHere ? '#4f8' : (isSelected ? '#4f4' : '#aaa'));
                html += `<div style="padding:4px 6px; margin:2px 0; border-radius:4px; cursor:pointer; display:flex; justify-content:space-between; align-items:center; background:${bgColor};" onclick="handleLevel2Click('${c.id}')">
                    <span style="color:${textColor};">${isHere ? '📍' : (isTarget ? '🎯 ' : '')}${c.name}</span>
                    <div>
                        <button class="cmd-btn" style="padding:1px 6px; font-size:10px; background:#226; margin-right:3px;" onclick="event.stopPropagation(); renameMapNode('${c.id}', '${c.name}')">✏️</button>
                        <button class="cmd-btn" style="padding:1px 6px; font-size:10px; background:#a22;" onclick="event.stopPropagation(); deleteMapNode('${c.id}')">🗑️</button>
                    </div>
                </div>`;
            });
            container.innerHTML = html;
        }

        function handleLevel2Click(id) {
            const region = (mapDataCache.regions || []).find(r => r.id === currentMapParent1);
            if (!region) return;
            const city = (region.children || []).find(c => c.id === id);
            if (!city) return;
            const wasSelected = id === currentMapParent2;
            selectMapLevel2(id);
            if (wasSelected) {
                setMapTarget(2, id, region.name, city.name, '');
            }
        }

        function selectMapLevel2(id) {
            currentMapParent2 = id;
            renderMapLevel2();
            renderMapLevel3();
            document.getElementById('add-level3-btn').disabled = false;
        }

        function renderMapLevel3() {
            const container = document.getElementById('map-level3');
            if (!currentMapParent2) {
                container.innerHTML = '<span style="color:#666;">请先选择城市</span>';
                return;
            }
            const region = (mapDataCache.regions || []).find(r => r.id === currentMapParent1);
            if (!region) { container.innerHTML = ''; return; }
            const city = (region.children || []).find(c => c.id === currentMapParent2);
            if (!city || !city.children || city.children.length === 0) {
                container.innerHTML = '<span style="color:#666;">暂无地点</span>';
                return;
            }
            let html = '';
            city.children.forEach(l => {
                const isTarget = currentMapTarget && currentMapTarget.id === l.id;
                const isHere = currentLocation && (currentLocation.includes(l.name) || l.name.includes(currentLocation));
                const bgColor = isTarget ? '#331' : (isHere ? '#133' : 'transparent');
                const textColor = isTarget ? '#ff4' : (isHere ? '#4f8' : '#aaa');
                html += `<div style="padding:4px 6px; margin:2px 0; border-radius:4px; cursor:pointer; display:flex; justify-content:space-between; align-items:center; background:${bgColor};" onclick="handleLevel3Click('${l.id}')">
                    <span style="color:${textColor};">${isHere ? '📍' : (isTarget ? '🎯 ' : '')}${l.name}</span>
                    <div>
                        <button class="cmd-btn" style="padding:1px 6px; font-size:10px; background:#226; margin-right:3px;" onclick="event.stopPropagation(); renameMapNode('${l.id}', '${l.name}')">✏️</button>
                        <button class="cmd-btn" style="padding:1px 6px; font-size:10px; background:#a22;" onclick="event.stopPropagation(); deleteMapNode('${l.id}')">🗑️</button>
                    </div>
                </div>`;
            });
            container.innerHTML = html;
        }

        function handleLevel3Click(id) {
            const region = (mapDataCache.regions || []).find(r => r.id === currentMapParent1);
            if (!region) return;
            const city = (region.children || []).find(c => c.id === currentMapParent2);
            if (!city) return;
            const location = (city.children || []).find(l => l.id === id);
            if (!location) return;
            setMapTarget(3, id, region.name, city.name, location.name);
        }

        async function addMapNode(level, parentId) {
            const name = prompt('请输入名称：');
            if (!name || !name.trim()) return;
            try {
                const res = await fetch('/map/add', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({level: level, parent_id: parentId, name: name.trim()})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    mapDataCache = data.data;
                    renderMapLevel1();
                    if (currentMapParent1) renderMapLevel2();
                    if (currentMapParent2) renderMapLevel3();
                } else {
                    alert('添加失败：' + data.message);
                }
            } catch(e) {
                alert('添加失败：' + e);
            }
        }

        async function renameMapNode(nodeId, oldName) {
            const newName = prompt('请输入新名称：', oldName);
            if (!newName || !newName.trim() || newName.trim() === oldName) return;
            try {
                const res = await fetch('/map/rename', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({node_id: nodeId, new_name: newName.trim()})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    mapDataCache = data.data;
                    renderMapLevel1();
                    if (currentMapParent1) renderMapLevel2();
                    if (currentMapParent2) renderMapLevel3();
                    updateMapTargetDisplay();
                } else {
                    alert('重命名失败：' + data.message);
                }
            } catch(e) {
                alert('重命名失败：' + e);
            }
        }

        async function deleteMapNode(nodeId) {
            if (!confirm('确定要删除这个节点吗？子节点也会一并删除。')) return;
            try {
                const res = await fetch('/map/delete', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({node_id: nodeId})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    mapDataCache = data.data;
                    // 清理已删除的选中项
                    if (currentMapParent1 === nodeId) { currentMapParent1 = ''; currentMapParent2 = ''; document.getElementById('add-level2-btn').disabled = true; document.getElementById('add-level3-btn').disabled = true; }
                    if (currentMapParent2 === nodeId) { currentMapParent2 = ''; document.getElementById('add-level3-btn').disabled = true; }
                    renderMapLevel1();
                    renderMapLevel2();
                    renderMapLevel3();
                    updateMapTargetDisplay();
                } else {
                    alert('删除失败：' + data.message);
                }
            } catch(e) {
                alert('删除失败：' + e);
            }
        }

        async function setMapTarget(level, id, region, city, location) {
            // 如果点击已选中的，取消选中
            if (currentMapTarget && currentMapTarget.id === id) {
                try {
                    const res = await fetch('/map/set_target', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({level: level, id: '', region: '', city: '', location: ''})
                    });
                    const data = await res.json();
                    if (data.status === 'success') {
                        currentMapTarget = null;
                        renderMapLevel1();
                        renderMapLevel2();
                        renderMapLevel3();
                        updateMapTargetDisplay();
                    }
                } catch(e) { console.error(e); }
                return;
            }
            try {
                const res = await fetch('/map/set_target', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({level: level, id: id, region: region, city: city, location: location})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    currentMapTarget = data.target;
                    renderMapLevel1();
                    renderMapLevel2();
                    renderMapLevel3();
                    updateMapTargetDisplay();
                }
            } catch(e) {
                alert('设置失败：' + e);
            }
        }

        function searchMapNodes(keyword) {
            const resultsDiv = document.getElementById('map-search-results');
            if (!keyword || !keyword.trim() || !mapDataCache) {
                resultsDiv.style.display = 'none';
                resultsDiv.innerHTML = '';
                return;
            }
            const kw = keyword.trim().toLowerCase();
            const results = [];
            const regions = mapDataCache.regions || [];
            
            regions.forEach(region => {
                // 检查一级区域
                if (region.name.toLowerCase().includes(kw)) {
                    results.push({
                        level: 1,
                        id: region.id,
                        name: region.name,
                        path: region.name,
                        parent1: region.id,
                        parent2: null
                    });
                }
                // 检查二级城市
                (region.children || []).forEach(city => {
                    if (city.name.toLowerCase().includes(kw)) {
                        results.push({
                            level: 2,
                            id: city.id,
                            name: city.name,
                            path: `${region.name} → ${city.name}`,
                            parent1: region.id,
                            parent2: city.id
                        });
                    }
                    // 检查三级地点
                    (city.children || []).forEach(location => {
                        if (location.name.toLowerCase().includes(kw)) {
                            results.push({
                                level: 3,
                                id: location.id,
                                name: location.name,
                                path: `${region.name} → ${city.name} → ${location.name}`,
                                parent1: region.id,
                                parent2: city.id
                            });
                        }
                    });
                });
            });
            
            if (results.length === 0) {
                resultsDiv.innerHTML = '<div style="padding:8px; color:#666; text-align:center;">未找到匹配的地点</div>';
            } else {
                resultsDiv.innerHTML = results.map(r => `
                    <div style="padding:6px 10px; cursor:pointer; border-bottom:1px solid #333; color:#aaa; font-size:12px;" 
                        onmouseover="this.style.background='#224'" onmouseout="this.style.background='transparent'"
                        onclick="jumpToSearchResult(${r.level}, '${r.id}', '${r.parent1}', ${r.parent2 ? "'" + r.parent2 + "'" : 'null'})">
                        <span style="color:${r.level===1?'#4ff':r.level===2?'#4f4':'#aaa'};">${'📌'.repeat(r.level)}</span> ${r.path}
                    </div>
                `).join('');
            }
            resultsDiv.style.display = 'block';
        }

        function jumpToSearchResult(level, id, parent1, parent2) {
            // 先选择一级
            currentMapParent1 = parent1;
            currentMapParent2 = '';
            renderMapLevel1();
            renderMapLevel2();
            renderMapLevel3();
            
            // 如果是二级或三级，选择二级
            if (level >= 2 && parent2) {
                currentMapParent2 = parent2;
                renderMapLevel2();
                renderMapLevel3();
            }
            
            // 关闭搜索结果
            document.getElementById('map-search-results').style.display = 'none';
            document.getElementById('map-search-input').value = '';
            
            // 滚动到地图区域
            document.getElementById('map-panel').scrollIntoView({behavior: 'smooth', block: 'start'});
        }
        // ======= 记事本 JavaScript =======
        function toggleNotepad() {
            const modal = document.getElementById('notepad-modal');
            if (modal.style.display === 'none' || !modal.style.display) {
                modal.style.display = 'block';
                notepadLoadRaw();
            } else {
                modal.style.display = 'none';
            }
        }

        async function notepadLoadRaw() {
            try {
                const res = await fetch('/notepad/raw');
                const data = await res.json();
                if (data.status === 'success') {
                    document.getElementById('notepad_editor').value = data.content || '';
                } else {
                    alert('加载失败：' + data.message);
                }
            } catch(e) {
                alert('网络错误：' + e);
            }
        }

        async function notepadSaveRaw() {
            if(!confirm('确定要保存修改吗？')) return;
            try {
                const raw = document.getElementById('notepad_editor').value;
                const res = await fetch('/notepad/raw_save', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({content: raw})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    alert('保存成功！');
                } else {
                    alert('保存失败：' + data.message);
                }
            } catch(e) {
                alert('保存失败：' + e);
            }
        }
        // ======= MD 文档编辑 JavaScript =======
        async function mdList() {
            try {
                const res = await fetch('/md/list');
                const data = await res.json();
                const sel = document.getElementById('md_selector');
                sel.innerHTML = '<option value="">-- 选择项目目录下的 .md 文件 --</option>';
                if (data.status === 'success') {
                    (data.files || []).forEach(f => {
                        const opt = document.createElement('option');
                        opt.value = f;
                        opt.textContent = f;
                        sel.appendChild(opt);
                    });
                } else {
                    alert('列表加载失败：' + data.message);
                }
            } catch(e) {
                alert('列表加载失败：' + e);
            }
        }
        async function mdLoad() {
            const p = document.getElementById('md_selector').value;
            if (!p) { alert('请先选择一个MD文件'); return; }
            try {
                const res = await fetch('/md/read?path=' + encodeURIComponent(p));
                const data = await res.json();
                if (data.status === 'success') {
                    document.getElementById('notepad_editor').value = data.content || '';
                } else {
                    alert('读取失败：' + data.message);
                }
            } catch(e) {
                alert('读取失败：' + e);
            }
        }
        async function mdSave() {
            const p = document.getElementById('md_selector').value;
            if (!p) { alert('请先选择一个MD文件'); return; }
            if(!confirm('确定要保存 MD 文件 ' + p + ' 吗？')) return;
            try {
                const content = document.getElementById('notepad_editor').value;
                const res = await fetch('/md/save', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({path: p, content: content})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    alert(data.message || '保存成功');
                } else {
                    alert('保存失败：' + data.message);
                }
            } catch(e) {
                alert('保存失败：' + e);
            }
        }

        function escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str || '';
            return div.innerHTML;
        }
        // ======= NPC 管理器 JavaScript =======
        let npcList = [];
        let playerName = '';  // 玩家姓名（供头像注入使用，与NPC头像同路径）
        let npcCurrentName = null;

        function toggleNpcManager() {
            const modal = document.getElementById('npc-manager-modal');
            if (modal.style.display === 'none' || !modal.style.display) {
                modal.style.display = 'block';
                npcRefresh();
            } else {
                modal.style.display = 'none';
            }
        }

        async function npcRefresh() {
            try {
                const res = await fetch('/npc/list');
                const data = await res.json();
                if (data.status === 'success') {
                    npcList = data.npc_list || [];
                    renderNpcList();
                } else {
                    alert('加载失败：' + data.message);
                }
            } catch(e) {
                alert('网络错误：' + e);
            }
        }

        function renderNpcList() {
            const list = document.getElementById('npc-list');
            const count = document.getElementById('npc-count');
            const keyword = (document.getElementById('npc-search').value || '').toLowerCase();
            
            const filtered = keyword ? npcList.filter(n => 
                (n.name || '').toLowerCase().includes(keyword) ||
                (n.identity || '').toLowerCase().includes(keyword)
            ) : npcList;
            
            count.textContent = filtered.length;
            
            if (filtered.length === 0) {
                list.innerHTML = '<div style="padding:20px; color:#555; text-align:center;">暂无NPC</div>';
                return;
            }
            
            let html = '';
            filtered.forEach((npc, idx) => {
                const isSelected = npc.name === npcCurrentName;
                html += `
                    <div style="padding:10px 12px; border-bottom:1px solid #223; cursor:pointer; 
                        background:${isSelected ? '#2a4' : 'transparent'}; 
                        color:${isSelected ? '#fff' : '#8af'};" 
                        onclick="npcSelect('${escapeHtml(npc.name)}')">
                        <div style="font-weight:bold;">${idx + 1}. ${escapeHtml(npc.name)}</div>
                        <div style="font-size:11px; color:#668; margin-top:3px;">${escapeHtml(npc.identity || '未知身份')}</div>
                    </div>
                `;
            });
            list.innerHTML = html;
        }

        function filterNpcList() {
            renderNpcList();
        }

        async function npcSelect(name) {
            npcCurrentName = name;
            document.getElementById('npc-editor-title').textContent = '编辑NPC：' + name;
            document.getElementById('npc-editor-header').style.display = 'block';
            document.getElementById('npc-editor-empty').style.display = 'none';
            renderNpcList();
            
            try {
                const res = await fetch('/npc/get?name=' + encodeURIComponent(name));
                const data = await res.json();
                if (data.status === 'success') {
                    document.getElementById('npc-editor').value = JSON.stringify(data.npc, null, 2);
                    renderNpcVitalityPanel(data.npc);
                } else {
                    alert('加载失败：' + data.message);
                }
            } catch(e) {
                alert('加载失败：' + e);
            }
        }

        function renderNpcVitalityPanel(npc) {
            const vit = (npc && npc.vitality && typeof npc.vitality === 'object') ? npc.vitality : {hp: 100, mp: 100, poisoned: false};
            let hp = parseInt(vit.hp); if (isNaN(hp)) hp = 100;
            let mp = parseInt(vit.mp); if (isNaN(mp)) mp = 100;
            const hpInput = document.getElementById('npc-hp-input');
            const mpInput = document.getElementById('npc-mp-input');
            const hpBar = document.getElementById('npc-hp-bar');
            const mpBar = document.getElementById('npc-mp-bar');
            if (!hpInput || !mpInput || !hpBar || !mpBar) return;
            hpInput.value = hp;
            mpInput.value = mp;
            const hpDisplay = hp < 0 ? 0 : hp;
            hpBar.style.width = Math.max(0, Math.min(100, hpDisplay)) + '%';
            hpBar.style.background = hp < 0 ? '#555' : (hp === 0 ? '#833' : 'linear-gradient(90deg,#f44,#f88)');
            mpBar.style.width = Math.max(0, Math.min(100, mp)) + '%';
        }

        function npcVitalityApply() {
            const hp = parseInt(document.getElementById('npc-hp-input').value);
            const mp = parseInt(document.getElementById('npc-mp-input').value);
            if (isNaN(hp) || hp < -1 || hp > 100) { alert('HP 范围：-1（已故）~ 100'); return; }
            if (isNaN(mp) || mp < 0 || mp > 100) { alert('MP 范围：0 ~ 100'); return; }
            let npcData;
            try {
                npcData = JSON.parse(document.getElementById('npc-editor').value);
            } catch(e) {
                alert('JSON 格式错误，无法应用：' + e);
                return;
            }
            npcData.vitality = {hp: hp, mp: mp, poisoned: !!(npcData.vitality && npcData.vitality.poisoned)};
            document.getElementById('npc-editor').value = JSON.stringify(npcData, null, 2);
            renderNpcVitalityPanel(npcData);
        }

        async function npcSave() {
            let npcData;
            try {
                npcData = JSON.parse(document.getElementById('npc-editor').value);
            } catch(e) {
                alert('JSON 格式错误：' + e);
                return;
            }
            if (!npcData.name) {
                alert('JSON 缺少 name 字段');
                return;
            }
            if (!confirm('确定要保存吗？')) return;

            // npcCurrentName 为 null 时走新增（AI草稿/手动新建），否则走更新
            if (!npcCurrentName) {
                try {
                    const res = await fetch('/npc/add', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            name: npcData.name,
                            identity: npcData.identity || '江湖人士',
                            initial_favor: typeof npcData.initial_favor === 'number' ? npcData.initial_favor : 15
                        })
                    });
                    const data = await res.json();
                    if (data.status !== 'success') {
                        alert('新增失败：' + data.message);
                        return;
                    }
                    // 新增成功后再用 update 写入完整数据
                    const res2 = await fetch('/npc/update', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({name: npcData.name, npc: npcData})
                    });
                    const data2 = await res2.json();
                    if (data2.status === 'success') {
                        alert('保存成功！');
                        npcCurrentName = npcData.name;
                        document.getElementById('npc-editor-title').textContent = '编辑NPC：' + npcData.name;
                        npcRefresh();
                    } else {
                        alert('完整数据写入失败（NPC已创建）：' + data2.message);
                        npcRefresh();
                    }
                } catch(e) {
                    alert('保存失败：' + e);
                }
                return;
            }

            try {
                const res = await fetch('/npc/update', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: npcCurrentName, npc: npcData})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    alert('保存成功！');
                    // 若改名了，同步当前选中名
                    if (npcData.name && npcData.name !== npcCurrentName) {
                        npcCurrentName = npcData.name;
                    }
                    npcRefresh();
                } else {
                    alert('保存失败：' + data.message);
                }
            } catch(e) {
                alert('保存失败：' + e);
            }
        }

        async function npcDelete() {
            if (!npcCurrentName) {
                alert('请先选择一个NPC');
                return;
            }
            if (!confirm('确定要删除NPC「' + npcCurrentName + '」吗？此操作不可恢复！')) return;
            
            try {
                const res = await fetch('/npc/delete', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: npcCurrentName})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    alert('删除成功！');
                    npcCurrentName = null;
                    document.getElementById('npc-editor-header').style.display = 'none';
                    document.getElementById('npc-editor-empty').style.display = 'flex';
                    npcRefresh();
                } else {
                    alert('删除失败：' + data.message);
                }
            } catch(e) {
                alert('删除失败：' + e);
            }
        }

        function npcClearEditor() {
            if (!confirm('确定要清空编辑器吗？')) return;
            document.getElementById('npc-editor').value = '';
        }

        async function npcGenerateAvatar() {
            if (!npcCurrentName) { alert('请先在左侧选择NPC'); return; }
            if (!confirm(`为「${npcCurrentName}」生成头像？\n将调用 Kolors API，约需10-20秒\n已有头像将被覆盖`)) return;
            const btn = event.target;
            btn.disabled = true; btn.textContent = '⏳ 生成中...';
            try {
                const res = await fetch('/npc/generate_avatar', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: npcCurrentName})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    alert(`头像已生成：${data.path}`);
                    npcRefresh();
                } else {
                    alert('生成失败：' + data.message);
                }
            } catch(e) {
                alert('生成失败：' + e);
            } finally {
                btn.disabled = false; btn.textContent = '🖼️ 生成头像';
            }
        }

        async function npcAddNew() {
            const name = prompt('请输入NPC姓名：');
            if (!name) return;
            const identity = prompt('请输入NPC身份：') || '江湖人士';
            const fav = parseInt(prompt('请输入初始好感（-100~100）：') || '15');
            
            try {
                const res = await fetch('/npc/add', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: name, identity: identity, initial_favor: fav})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    alert('创建成功！');
                    npcRefresh();
                    npcSelect(name);
                } else {
                    alert('创建失败：' + data.message);
                }
            } catch(e) {
                alert('创建失败：' + e);
            }
        }

        async function npcAiGenerate() {
            const descInput = document.getElementById('npc-ai-desc');
            const desc = (descInput.value || '').trim();
            if (!desc) {
                alert('请输入人物描述词');
                descInput.focus();
                return;
            }
            // 确保编辑器区域可见
            document.getElementById('npc-editor-header').style.display = 'block';
            document.getElementById('npc-editor-empty').style.display = 'none';
            const ta = document.getElementById('npc-editor');
            ta.value = '⏳ AI 正在生成，请稍候...';
            const btn = event ? event.target : null;
            if (btn) { btn.disabled = true; btn.textContent = '生成中...'; }

            try {
                const res = await fetch('/npc/ai_generate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({desc: desc})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    ta.value = JSON.stringify(data.npc, null, 2);
                    npcCurrentName = null;  // 草稿模式，保存时走新增
                    document.getElementById('npc-editor-title').textContent = 'AI生成草稿（未保存）：请审核后点「💾 保存修改」';
                    alert('AI 生成完成！请审核 JSON 内容，确认无误后点「保存修改」（将作为新NPC入库）');
                } else {
                    ta.value = '';
                    alert('生成失败：' + data.message);
                }
            } catch(e) {
                ta.value = '';
                alert('生成失败：' + e);
            } finally {
                if (btn) { btn.disabled = false; btn.textContent = '⚡ AI生成'; }
            }
        }

        // ============ 📜 任务管理（镜像武功书弹窗架构，REST API 局部刷新） ============
        let taskList = [];

        function toggleTaskManager() {
            const m = document.getElementById('task-manager-modal');
            if (m.style.display === 'none') {
                m.style.display = 'block';
                document.getElementById('task-create-area').style.display = 'none';
                taskRefresh();
            } else {
                m.style.display = 'none';
            }
        }

        function taskRefresh() {
            fetch('/task/list')
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'success') {
                        taskList = data.tasks || [];
                        taskRender();
                    } else {
                        document.getElementById('task-list').innerHTML =
                            '<div style="color:#f66; padding:10px;">加载失败：' + (data.message || '未知错误') + '</div>';
                    }
                })
                .catch(e => {
                    document.getElementById('task-list').innerHTML =
                        '<div style="color:#f66; padding:10px;">网络错误：' + e + '</div>';
                });
        }

        function taskEsc(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }

        function taskRender() {
            const fStatus = document.getElementById('task-filter-status').value;
            const fType = document.getElementById('task-filter-type').value;
            const box = document.getElementById('task-list');
            let shown = 0;
            let html = '';
            taskList.forEach(t => {
                const status = t.status === 'completed' ? 'completed'
                             : (t.suspended ? 'suspended' : 'active');
                if (fStatus && status !== fStatus) return;
                if (fType && (t.type || 'side') !== fType) return;
                shown++;
                const isDone = t.status === 'completed';
                const pct = Math.max(0, Math.min(100, parseInt(t.progress_percent || 0, 10) || 0));
                const typeLabel = (t.type === 'main' ? '主线' : '支线');
                const typeColor = (t.type === 'main' ? '#fa8' : '#8af');
                const statusLabel = isDone ? '已完成' : (t.suspended ? '已暂停' : '进行中');
                const statusColor = isDone ? '#4f4' : (t.suspended ? '#ff4' : '#4ff');
                const doneStyle = isDone ? 'opacity:0.55;' : '';
                html += `
                <div style="background:#111; border:1px solid #345; border-radius:6px; padding:10px 12px; ${doneStyle}">
                    <div style="display:flex; flex-wrap:wrap; align-items:center; gap:6px 10px; margin-bottom:4px;">
                        <span style="color:#fff; font-weight:bold; font-size:14px;">${taskEsc(t.display_name || t.name)}</span>
                        <span style="color:#666; font-size:11px;">#${taskEsc(t.name)}</span>
                        <span style="color:${typeColor}; font-size:11px; border:1px solid ${typeColor}; border-radius:3px; padding:1px 6px;">${typeLabel}</span>
                        <span style="color:${statusColor}; font-size:11px;">● ${statusLabel}</span>
                        <span style="color:#555; font-size:10px; margin-left:auto;">${taskEsc(t.created_at || '')}</span>
                    </div>
                    <div style="color:#aaa; font-size:12px; margin:4px 0 6px 0; line-height:1.5;">${taskEsc(t.description || '')}</div>
                    <div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
                        <div style="flex:1; height:8px; background:#222; border-radius:4px; overflow:hidden;">
                            <div style="height:100%; width:${pct}%; background:linear-gradient(90deg,#4af,#4f4); border-radius:4px;"></div>
                        </div>
                        <span style="color:#4ff; font-size:12px; min-width:36px; text-align:right;">${pct}%</span>
                        <span style="color:#ff4; font-size:11px;">${taskEsc(t.current_stage || '未开始')}</span>
                    </div>
                    ${isDone ? '' : `
                    <div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-bottom:6px;">
                        <input type="number" id="task-pct-${taskEsc(t.name)}" min="0" max="100" value="${pct}"
                               style="width:64px; padding:4px 6px; background:#222; color:#0f0; border:1px solid #4a6; border-radius:4px; font-size:11px;">
                        <input type="text" id="task-stage-${taskEsc(t.name)}" value="${taskEsc(t.current_stage || '')}" placeholder="阶段描述"
                               style="flex:1; min-width:120px; padding:4px 6px; background:#222; color:#0f0; border:1px solid #4a6; border-radius:4px; font-size:11px;">
                        <button onclick="taskProgress('${taskEsc(t.name)}')" class="cmd-btn" style="background:#448; font-size:11px;">💾 更新进度</button>
                    </div>`}
                    <div style="display:flex; flex-wrap:wrap; gap:6px;">
                        <button onclick="taskAction('type','${taskEsc(t.name)}',{type:'${t.type === 'main' ? 'side' : 'main'}'})"
                                class="cmd-btn" style="background:#638; font-size:11px;">${t.type === 'main' ? '转支线' : '转主线'}</button>
                        ${isDone ? '' : `<button onclick="taskAction('suspend','${taskEsc(t.name)}')"
                                class="cmd-btn" style="background:#664; font-size:11px;">${t.suspended ? '▶ 恢复' : '⏸ 暂停'}</button>
                        <button onclick="taskAction('complete','${taskEsc(t.name)}')"
                                class="cmd-btn" style="background:#484; font-size:11px;">✅ 完成</button>`}
                        <button onclick="taskDelete('${taskEsc(t.name)}')"
                                class="cmd-btn" style="background:#833; font-size:11px;">🗑 删除</button>
                    </div>
                </div>`;
            });
            if (!shown) {
                html = '<div style="color:#888; padding:20px; text-align:center;">暂无任务（或筛选无结果）</div>';
            }
            box.innerHTML = html;
            document.getElementById('task-count').textContent = `共 ${shown} 项（总计 ${taskList.length}）`;
        }

        function taskFilter() { taskRender(); }

        function taskToggleCreate() {
            const a = document.getElementById('task-create-area');
            a.style.display = (a.style.display === 'none') ? 'block' : 'none';
        }

        function taskAiGenerate() {
            const intentEl = document.getElementById('task-ai-intent');
            const btn = document.getElementById('task-ai-btn');
            const intent = intentEl.value.trim();
            if (!intent) { alert('请先输入任务意图描述'); intentEl.focus(); return; }
            btn.disabled = true;
            btn.textContent = '⏳ 生成中...';
            fetch('/task/ai_generate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({intent: intent})
            })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success' && data.task) {
                    const t = data.task;
                    document.getElementById('task-new-name').value = t.display_name || '';
                    document.getElementById('task-new-desc').value = t.description || '';
                    document.getElementById('task-new-type').value = (t.type === 'main') ? 'main' : 'side';
                    if (t.current_stage) {
                        // 初始阶段暂存：创建后可在卡片中一键更新（表单无此字段）
                        window.__task_ai_stage = t.current_stage;
                        window.__task_ai_pct = t.progress_percent || 0;
                        console.log('[AI任务] 初始阶段：' + t.current_stage + '（' + (t.progress_percent || 0) + '%）—— 创建后可在进度栏填入');
                    }
                } else {
                    alert('生成失败：' + (data.message || '未知错误'));
                }
            })
            .catch(e => alert('网络错误：' + e))
            .finally(() => {
                btn.disabled = false;
                btn.textContent = '⚡ AI生成';
            });
        }

        function taskCreate() {
            const name = document.getElementById('task-new-name').value.trim();
            const desc = document.getElementById('task-new-desc').value.trim();
            const type = document.getElementById('task-new-type').value;
            if (!name || !desc) { alert('任务名称和描述不能为空'); return; }
            fetch('/task/create', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({display_name: name, description: desc, type: type})
            })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    document.getElementById('task-new-name').value = '';
                    document.getElementById('task-new-desc').value = '';
                    document.getElementById('task-create-area').style.display = 'none';
                    taskRefresh();
                } else { alert('创建失败：' + (data.message || '')); }
            })
            .catch(e => alert('网络错误：' + e));
        }

        function taskProgress(name) {
            const pctEl = document.getElementById('task-pct-' + name);
            const stageEl = document.getElementById('task-stage-' + name);
            if (!pctEl && !stageEl) return;
            const body = {name: name};
            if (pctEl && pctEl.value !== '') body.percent = parseInt(pctEl.value, 10);
            if (stageEl) body.stage = stageEl.value.trim();
            taskAction('progress', name, body);
        }

        function taskAction(action, name, extra) {
            fetch('/task/' + action, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(Object.assign({name: name}, extra || {}))
            })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    // 任务总结追加到主交互页面（与剧情文本同样式）
                    if (data.summary) {
                        append('【任务总结】 #' + name, "change");
                        append(data.summary, "plot");
                    }
                    taskRefresh();
                }
                else { alert('操作失败：' + (data.message || '')); }
            })
            .catch(e => alert('网络错误：' + e));
        }

        function taskDelete(name) {
            if (!confirm('确认删除任务 #' + name + '？不可恢复。')) return;
            taskAction('delete', name);
        }

        // ============ 武功书管理 ============
        let martialArts = [];
        let martialCurrentName = null;
        let martialMeta = {grade_system: {}, category_list: []};
        let martialEffectsList = [];   // 特效列表（来自 /martial/list_effect）
        let martialEffectDefaultRate = {attack:5, internal:8, lightfoot:6, special:4};
        const MARTIAL_GRADE_BONUS = {9:7, 8:6, 7:5, 6:4, 5:3, 4:2, 3:1, 2:0, 1:-1};
        const MARTIAL_CAT_NAMES = {
            internal:'内功', sword:'剑法', blade:'刀法', palm:'掌法', staff:'棍枪',
            lightfoot:'轻功', finger:'指腿', hidden:'暗器', fist:'拳法', special:'特殊'
        };

        function toggleMartialManager() {
            const m = document.getElementById('martial-manager-modal');
            if (m.style.display === 'none') {
                m.style.display = 'block';
                document.getElementById('martial-guide-view').style.display = 'none';
                martialInitDropdowns();
                martialRefresh();
            } else {
                m.style.display = 'none';
            }
        }

        function martialInitDropdowns() {
            // 等级筛选
            const gradeFilter = document.getElementById('martial-filter-grade');
            const editGrade = document.getElementById('martial-edit-grade');
            // 仅在首次初始化时填充
            if (gradeFilter.options.length <= 1) {
                for (let g = 9; g >= 1; g--) {
                    const o1 = document.createElement('option'); o1.value = g; o1.text = g + '级'; gradeFilter.appendChild(o1);
                    const o2 = document.createElement('option'); o2.value = g; o2.text = g + '级'; editGrade.appendChild(o2);
                }
            }
            // 类别筛选
            const catFilter = document.getElementById('martial-filter-cat');
            const editCat = document.getElementById('martial-edit-category');
            if (catFilter.options.length <= 1) {
                const cats = Object.keys(MARTIAL_CAT_NAMES);
                cats.forEach(c => {
                    const o1 = document.createElement('option'); o1.value = c; o1.text = MARTIAL_CAT_NAMES[c]; catFilter.appendChild(o1);
                    const o2 = document.createElement('option'); o2.value = c; o2.text = MARTIAL_CAT_NAMES[c] + ' (' + c + ')'; editCat.appendChild(o2);
                });
            }
            // 特效下拉框初始化（异步加载）
            martialInitEffectDropdown();
        }

        async function martialInitEffectDropdown() {
            const sel = document.getElementById('martial-edit-effect-type');
            if (!sel) return;
            // 仅在首次初始化时拉取
            if (sel.options.length > 1) return;
            try {
                const res = await fetch('/martial/list_effect');
                const data = await res.json();
                if (data.status !== 'success') return;
                martialEffectsList = data.effects || [];
                martialEffectDefaultRate = data.default_base_rate || martialEffectDefaultRate;
                // 按 effects 顺序追加（首项已是"无特效"）
                martialEffectsList.forEach(eff => {
                    if (eff.id === '') return; // 跳过占位项（HTML已默认）
                    const o = document.createElement('option');
                    o.value = eff.id;
                    o.text = eff.name + ' (' + eff.category + ')';
                    o.dataset.desc = eff.desc || '';
                    o.dataset.category = eff.category || '';
                    sel.appendChild(o);
                });
            } catch(e) {
                console.error('加载特效列表失败:', e);
            }
        }

        function martialOnEffectChange() {
            const sel = document.getElementById('martial-edit-effect-type');
            const descDiv = document.getElementById('martial-effect-desc');
            const rateInput = document.getElementById('martial-edit-base-rate');
            const selectedId = sel.value;
            // 找到选中项的元数据
            const eff = martialEffectsList.find(e => e.id === selectedId);
            if (eff && eff.desc) {
                descDiv.textContent = '📖 ' + eff.desc;
            } else {
                descDiv.textContent = '';
            }
            // 自动填充默认基础率（仅当当前基础率为空或与上次默认一致时）
            if (eff && eff.category && martialEffectDefaultRate[eff.category] !== undefined) {
                const defaultRate = martialEffectDefaultRate[eff.category];
                // 如果输入框为空或是上次默认值,自动更新为新类别的默认值
                const cur = parseInt(rateInput.value) || 0;
                if (!cur || Object.values(martialEffectDefaultRate).includes(cur)) {
                    rateInput.value = defaultRate;
                }
            }
        }

        function martialUpdateBonusPreview() {
            const g = parseInt(document.getElementById('martial-edit-grade').value) || 4;
            document.getElementById('martial-edit-bonus').value = MARTIAL_GRADE_BONUS[g] ?? 0;
        }

        async function martialRefresh() {
            try {
                const res = await fetch('/martial/meta');
                const md = await res.json();
                if (md.status === 'success') {
                    martialMeta = md;
                }
                martialSearch();
            } catch(e) {
                alert('加载元数据失败：' + e);
            }
        }

        async function martialShowGuide() {
            // 显示武功品阶评判标准文档
            document.getElementById('martial-editor').style.display = 'none';
            document.getElementById('martial-editor-empty').style.display = 'none';
            const guideView = document.getElementById('martial-guide-view');
            const content = document.getElementById('martial-guide-content');
            guideView.style.display = 'flex';
            content.textContent = '加载中...';
            try {
                const res = await fetch('/martial/guide');
                const data = await res.json();
                if (data.status === 'success') {
                    content.textContent = data.content;
                } else {
                    content.textContent = '加载失败：' + (data.msg || '未知错误');
                }
            } catch(e) {
                content.textContent = '加载失败：' + e;
            }
        }

        function martialHideGuide() {
            // 返回武功编辑视图
            document.getElementById('martial-guide-view').style.display = 'none';
            const editor = document.getElementById('martial-editor');
            if (editor.style.display === 'block') {
                // 当前有选中武功，保持编辑器显示
            } else {
                document.getElementById('martial-editor-empty').style.display = 'flex';
            }
        }

        async function martialSearch() {
            const keyword = document.getElementById('martial-search').value;
            const grade = document.getElementById('martial-filter-grade').value;
            const cat = document.getElementById('martial-filter-cat').value;
            try {
                const params = new URLSearchParams();
                if (keyword) params.append('keyword', keyword);
                if (grade) params.append('grade', grade);
                if (cat) params.append('category', cat);
                const res = await fetch('/martial/list?' + params.toString());
                const data = await res.json();
                if (data.status === 'success') {
                    martialArts = data.arts || [];
                    martialRenderList();
                } else {
                    alert('加载失败：' + data.message);
                }
            } catch(e) {
                alert('网络错误：' + e);
            }
        }

        function martialRenderList() {
            const list = document.getElementById('martial-list');
            const count = document.getElementById('martial-count');
            count.textContent = '共 ' + martialArts.length + ' 项';
            if (martialArts.length === 0) {
                list.innerHTML = '<div style="padding:20px; color:#555; text-align:center;">无匹配结果</div>';
                return;
            }
            const gradeColors = {9:'#f44', 8:'#f84', 7:'#fa4', 6:'#ff4', 5:'#8f4', 4:'#4f8', 3:'#48f', 2:'#a8f', 1:'#888'};
            let html = '';
            martialArts.forEach((a, idx) => {
                const c = gradeColors[a.grade] || '#888';
                const catName = MARTIAL_CAT_NAMES[a.category] || a.category;
                const sel = (a.name === martialCurrentName) ? 'background:#334;' : '';
                html += `<div data-idx="${idx}" class="martial-row" style="padding:6px 10px; cursor:pointer; border-bottom:1px solid #234; ${sel}">`;
                html += `<div style="display:flex; justify-content:space-between; align-items:center;">`;
                html += `<span style="color:#df8; font-size:13px;">${escapeHtml(a.name)}</span>`;
                html += `<span style="color:${c}; font-size:11px;">[${a.grade}级 +${a.bonus}]</span>`;
                html += `</div>`;
                html += `<div style="color:#888; font-size:10px; margin-top:2px;">${catName} · ${escapeHtml(a.source || '—')}</div>`;
                if (a.brief_desc) {
                    html += `<div style="color:#aba; font-size:10px; margin-top:1px;">${escapeHtml(a.brief_desc)}</div>`;
                }
                html += `</div>`;
            });
            list.innerHTML = html;
            list.querySelectorAll('.martial-row').forEach(el => {
                el.onclick = function() {
                    const idx = parseInt(this.getAttribute('data-idx'));
                    if (!isNaN(idx) && martialArts[idx]) {
                        martialSelect(martialArts[idx].name);
                    }
                };
            });
        }

        async function martialSelect(name) {
            martialCurrentName = name;
            try {
                // 确保特效下拉框已初始化（异步加载等待）
                await martialInitEffectDropdown();
                const res = await fetch('/martial/get?name=' + encodeURIComponent(name));
                const data = await res.json();
                if (data.status !== 'success') {
                    alert('加载失败：' + data.message);
                    return;
                }
                const a = data.art;
                document.getElementById('martial-edit-name').value = a.name;
                document.getElementById('martial-edit-grade').value = a.grade;
                document.getElementById('martial-edit-category').value = a.category;
                document.getElementById('martial-edit-source').value = a.source;
                document.getElementById('martial-edit-note').value = a.note || '';
                document.getElementById('martial-edit-brief').value = a.brief_desc || '';
                // 特效回填
                const effectType = (a.effect && a.effect.type) ? a.effect.type : '';
                const baseRate = (a.effect && a.effect.base_rate) ? a.effect.base_rate : 5;
                document.getElementById('martial-edit-effect-type').value = effectType;
                document.getElementById('martial-edit-base-rate').value = baseRate;
                const snEl = document.getElementById('martial-edit-special-name');
                const sdEl = document.getElementById('martial-edit-special-desc');
                if (snEl) snEl.value = a.special_move_name || '';
                if (sdEl) sdEl.value = a.special_move_desc || '';
                martialOnEffectChange();
                martialUpdateBonusPreview();
                document.getElementById('martial-editor').style.display = 'block';
                document.getElementById('martial-editor-empty').style.display = 'none';
                document.getElementById('martial-guide-view').style.display = 'none';
                martialRenderList();
            } catch(e) {
                alert('网络错误：' + e);
            }
        }

        async function martialAiGenerate() {
            const descInput = document.getElementById('martial-ai-desc');
            const desc = (descInput.value || '').trim();
            if (!desc) { alert('请输入武功描述词'); descInput.focus(); return; }

            // 确保编辑器可见
            document.getElementById('martial-editor').style.display = 'block';
            document.getElementById('martial-editor-empty').style.display = 'none';
            document.getElementById('martial-guide-view').style.display = 'none';

            const btn = event ? event.target : null;
            if (btn) { btn.disabled = true; btn.textContent = '生成中...'; }

            try {
                const res = await fetch('/martial/ai_generate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({desc: desc})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    const a = data.art;
                    // 拆解JSON到各个表单字段
                    document.getElementById('martial-edit-name').value = a.name || '';
                    document.getElementById('martial-edit-grade').value = a.grade || 4;
                    martialUpdateBonusPreview();  // 自动计算bonus
                    document.getElementById('martial-edit-category').value = a.category || 'fist';
                    document.getElementById('martial-edit-source').value = a.source || '';
                    document.getElementById('martial-edit-note').value = a.note || '';
                    document.getElementById('martial-edit-brief').value = a.brief_desc || '';

                    // 特效配置自动选择
                    const effectType = (a.effect && a.effect.type) ? a.effect.type : '';
                    document.getElementById('martial-edit-effect-type').value = effectType;
                    if (a.effect && a.effect.base_rate) {
                        document.getElementById('martial-edit-base-rate').value = a.effect.base_rate;
                    }
                    martialOnEffectChange();  // 刷新特效说明和默认基础率

                    // 特技名称/描述自动填写
                    document.getElementById('martial-edit-special-name').value = a.special_move_name || '';
                    document.getElementById('martial-edit-special-desc').value = a.special_move_desc || '';

                    martialCurrentName = null;  // 标记为新增草稿
                    alert('AI 生成完成！请审核各字段，确认无误后点「💾 保存」');
                } else {
                    alert('生成失败：' + data.message);
                }
            } catch(e) {
                alert('生成失败：' + e);
            } finally {
                if (btn) { btn.disabled = false; btn.textContent = '⚡ AI生成'; }
            }
        }

        function martialAddNew() {
            martialCurrentName = null;
            document.getElementById('martial-edit-name').value = '';
            document.getElementById('martial-edit-grade').value = '4';
            document.getElementById('martial-edit-category').value = 'fist';
            document.getElementById('martial-edit-source').value = '';
            document.getElementById('martial-edit-note').value = '';
            document.getElementById('martial-edit-brief').value = '';
            // 清空特效
            document.getElementById('martial-edit-effect-type').value = '';
            document.getElementById('martial-edit-base-rate').value = 5;
            const snEl2 = document.getElementById('martial-edit-special-name');
            const sdEl2 = document.getElementById('martial-edit-special-desc');
            if (snEl2) snEl2.value = '';
            if (sdEl2) sdEl2.value = '';
            martialOnEffectChange();
            martialUpdateBonusPreview();
            document.getElementById('martial-editor').style.display = 'block';
            document.getElementById('martial-editor-empty').style.display = 'none';
            document.getElementById('martial-guide-view').style.display = 'none';
            document.getElementById('martial-edit-name').focus();
        }

        function martialClearEditor() {
            martialCurrentName = null;
            document.getElementById('martial-edit-name').value = '';
            document.getElementById('martial-edit-grade').value = '4';
            document.getElementById('martial-edit-category').value = 'fist';
            document.getElementById('martial-edit-source').value = '';
            document.getElementById('martial-edit-note').value = '';
            document.getElementById('martial-edit-brief').value = '';
            // 清空特效
            document.getElementById('martial-edit-effect-type').value = '';
            document.getElementById('martial-edit-base-rate').value = 5;
            const snEl3 = document.getElementById('martial-edit-special-name');
            const sdEl3 = document.getElementById('martial-edit-special-desc');
            if (snEl3) snEl3.value = '';
            if (sdEl3) sdEl3.value = '';
            martialOnEffectChange();
            martialUpdateBonusPreview();
            document.getElementById('martial-editor').style.display = 'none';
            document.getElementById('martial-editor-empty').style.display = 'flex';
            martialRenderList();
        }

        async function martialSave() {
            const newName = document.getElementById('martial-edit-name').value.trim();
            if (!newName) { alert('武功名不能为空'); return; }
            const effectType = document.getElementById('martial-edit-effect-type').value.trim();
            let baseRate = parseInt(document.getElementById('martial-edit-base-rate').value);
            if (!baseRate || isNaN(baseRate)) baseRate = 5;
            if (baseRate < 1) baseRate = 1;
            if (baseRate > 20) baseRate = 20;
            const payload = {
                name: newName,
                grade: parseInt(document.getElementById('martial-edit-grade').value),
                category: document.getElementById('martial-edit-category').value,
                source: document.getElementById('martial-edit-source').value.trim(),
                note: document.getElementById('martial-edit-note').value.trim(),
                brief_desc: document.getElementById('martial-edit-brief').value.trim(),
                effect_type: effectType,
                base_rate: baseRate,
                special_move_name: document.getElementById('martial-edit-special-name').value.trim(),
                special_move_desc: document.getElementById('martial-edit-special-desc').value.trim()
            };
            try {
                let res, data;
                if (martialCurrentName) {
                    // 编辑（含重命名）
                    payload.old_name = martialCurrentName;
                    res = await fetch('/martial/update', {
                        method: 'POST', headers: {'Content-Type':'application/json'},
                        body: JSON.stringify(payload)
                    });
                } else {
                    // 新增
                    res = await fetch('/martial/add', {
                        method: 'POST', headers: {'Content-Type':'application/json'},
                        body: JSON.stringify(payload)
                    });
                }
                data = await res.json();
                if (data.status === 'success') {
                    alert('保存成功！');
                    martialCurrentName = newName;
                    martialSearch();
                } else {
                    alert('保存失败：' + data.message);
                }
            } catch(e) {
                alert('保存失败：' + e);
            }
        }

        async function martialDelete() {
            if (!martialCurrentName) { alert('请先选择武功'); return; }
            if (!confirm('确定要删除「' + martialCurrentName + '」吗？此操作不可撤销。')) return;
            try {
                const res = await fetch('/martial/delete', {
                    method: 'POST', headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({name: martialCurrentName})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    alert('已删除');
                    martialClearEditor();
                    martialSearch();
                } else {
                    alert('删除失败：' + data.message);
                }
            } catch(e) {
                alert('删除失败：' + e);
            }
        }

        // ================================================================
        //  🎒 物品书管理 JS（镜像武功书结构，字段名匹配 items_catalog.json）
        //  HTML ID 约定（请与上方HTML保持完全一致）：
        //   搜索区: item-search, item-filter-subcategory, item-filter-rarity
        //   列表区: item-list (div), item-count (统计栏)
        //   编辑区: item-editor(整体), item-editor-empty(空状态占位), item-guide-view(说明面板)
        //   编辑器字段: item-edit-name / item-edit-rarity / item-edit-subcategory
        //              item-edit-source / item-edit-owner-hint / item-edit-linked-martial
        //              item-edit-description / item-edit-keywords(逗号分隔) / item-edit-note
        //              item-edit-weight-preview(只读) / item-edit-original-name(hidden)
        // ================================================================
        let itemCurrentName = '';   // 当前编辑中的物品原名称（支持改名，对应item-edit-original-name）
        let itemRarityTier = {};    // 稀有度中文名 S/A/B/C/D → 释义
        let itemSubcategoryList = []; // 种类列表（秘籍/武器/防具/暗器/丹药/坐骑）
        let itemRarityWeight = {};  // 稀有度权重 S→3.0 等

        function toggleItemManager() {
            const m = document.getElementById('item-manager-modal');
            if (m.style.display === 'block') {
                m.style.display = 'none';
            } else {
                m.style.display = 'block';
                itemClearEditor();
                itemRefreshMeta();   // 首刷：填充下拉选项
                itemSearch();        // 首刷：列表
            }
        }

        async function itemRefreshMeta() {
            // 加载物品元数据并同步到：种类下拉、稀有度下拉、统计栏
            try {
                const res = await fetch('/items/meta');
                const data = await res.json();
                if (data.status === 'success') {
                    itemRarityTier = data.rarity_tier || {};
                    itemSubcategoryList = data.subcategory_list || [];
                    itemRarityWeight = data.rarity_weight || {};

                    // 辅助函数：填充 select（保留"全部"/"--选择--"占位选项）
                    function fillSelect(sel, options, placeholder) {
                        sel.innerHTML = '<option value="">' + placeholder + '</option>';
                        options.forEach(o => {
                            const ov = document.createElement('option');
                            ov.value = o.value; ov.textContent = o.label;
                            sel.appendChild(ov);
                        });
                    }
                    const scSel = document.getElementById('item-filter-subcategory');
                    const scEd = document.getElementById('item-edit-subcategory');
                    const rSel = document.getElementById('item-filter-rarity');
                    const rEd = document.getElementById('item-edit-rarity');
                    fillSelect(scSel, itemSubcategoryList.map(v=>({value:v,label:v})), '全部种类');
                    fillSelect(scEd, itemSubcategoryList.map(v=>({value:v,label:v})), '-- 选择种类 --');
                    const rOpts = Object.keys(itemRarityTier).map(k=>({
                        value: k,
                        label: `${k}（${itemRarityTier[k]} · 权重×${itemRarityWeight[k]||0}）`
                    }));
                    fillSelect(rSel, rOpts, '全部稀有度');
                    fillSelect(rEd, rOpts, '-- 选择稀有度 --');

                    // 顶栏统计
                    const count = data.total_count || 0;
                    const scText = Object.entries(data.subcategory_counts||{}).map(([k,v])=>`${k}:${v}`).join('  ') || '-';
                    const rText = Object.entries(data.rarity_counts||{}).map(([k,v])=>`${k}:${v}`).join('  ') || '-';
                    const cntDom = document.getElementById('item-count');
                    if (cntDom) cntDom.textContent = `共 ${count} 项 · ${scText} · 稀有度 ${rText}`;
                }
            } catch(e) { console.error('[items meta]', e); }
        }

        function itemRefresh() {
            // 手动刷新按钮：重载元数据+列表
            itemRefreshMeta();
            itemSearch();
        }

        async function itemSearch() {
            // 按关键字/种类/稀有度查询物品列表，结果渲染到 item-list div
            const search = document.getElementById('item-search').value.trim();
            const sc = document.getElementById('item-filter-subcategory').value;
            const r = document.getElementById('item-filter-rarity').value;
            const params = new URLSearchParams();
            if (search) params.append('search', search);
            if (sc) params.append('subcategory', sc);
            if (r) params.append('rarity', r);
            try {
                const res = await fetch('/items/list?' + params.toString());
                const data = await res.json();
                const listDiv = document.getElementById('item-list');
                listDiv.innerHTML = '';
                const cntDom = document.getElementById('item-count');
                if (data.status === 'success' && Array.isArray(data.items)) {
                    data.items.forEach(it => {
                        // 复用武功书列表样式类 martial-list-item / martial-list-title / martial-list-meta
                        const item = document.createElement('div');
                        item.className = 'martial-list-item';
                        const scTxt = it.subcategory || '';
                        item.innerHTML = `<div class="martial-list-title">${it.name}</div>
                            <div class="martial-list-meta">
                                <span class="martial-tag martial-tag-${it.rarity}">${it.rarity}·${scTxt}</span>
                                ${it.owner_hint ? `<span>🤝${it.owner_hint}</span>` : ''}
                                ${it.source ? `<span>📚${it.source}</span>` : ''}
                                ${it.linked_martial ? `<span>⚔️${it.linked_martial}</span>` : ''}
                            </div>`;
                        item.onclick = () => itemSelect(it.name);
                        listDiv.appendChild(item);
                    });
                    const baseCnt = data.items.length;
                    if (cntDom && cntDom.textContent && cntDom.textContent.startsWith('共 ')) {
                        // 已有meta信息，只更新查询到的数量前缀
                        const oldAfter = cntDom.textContent.split(' · ').slice(1).join(' · ');
                        cntDom.textContent = `查询到 ${baseCnt} 项` + (oldAfter ? ` · ${oldAfter}` : '');
                    } else if (cntDom) {
                        cntDom.textContent = `查询到 ${baseCnt} 项`;
                    }
                } else {
                    if (cntDom) cntDom.textContent = '查询失败：' + (data.msg||'未知错误');
                }
            } catch(e) {
                alert('查询失败：' + e);
            }
        }

        async function itemSelect(name) {
            // 点击列表项 → 加载详情到编辑器
            if (!name) return;
            try {
                const res = await fetch('/items/get?' + new URLSearchParams({name}));
                const data = await res.json();
                if (data.status === 'success') {
                    const it = data.item;
                    itemCurrentName = name;
                    document.getElementById('item-edit-original-name').value = name;
                    document.getElementById('item-edit-name').value = it.name || '';
                    document.getElementById('item-edit-subcategory').value = it.subcategory || '';
                    document.getElementById('item-edit-rarity').value = it.rarity || 'C';
                    document.getElementById('item-edit-description').value = it.description || '';
                    document.getElementById('item-edit-linked-martial').value = it.linked_martial || '';
                    document.getElementById('item-edit-source').value = it.source || '';
                    document.getElementById('item-edit-owner-hint').value = it.owner_hint || '';
                    document.getElementById('item-edit-note').value = it.note || '';
                    // 关键词后端返回数组，前端用逗号分隔展示
                    document.getElementById('item-edit-keywords').value =
                        (it.keywords && it.keywords.length ? it.keywords.join('，') : '');
                    itemUpdateRarityPreview();

                    // 切换到编辑器视图
                    document.getElementById('item-editor').style.display = 'block';
                    document.getElementById('item-editor-empty').style.display = 'none';
                    document.getElementById('item-guide-view').style.display = 'none';
                } else {
                    alert('加载详情失败：' + data.msg);
                }
            } catch(e) { alert('加载详情失败：' + e); }
        }

        function itemClearEditor() {
            // 清空编辑器：所有字段，切回空占位视图
            itemCurrentName = '';
            ['item-edit-name','item-edit-source','item-edit-owner-hint',
             'item-edit-linked-martial','item-edit-description','item-edit-note',
             'item-edit-keywords','item-edit-original-name','item-edit-weight-preview']
                .forEach(id => { const el=document.getElementById(id); if (el) el.value=''; });
            const sc = document.getElementById('item-edit-subcategory'); if (sc) sc.value = '';
            const r = document.getElementById('item-edit-rarity'); if (r) r.value = '';
            document.getElementById('item-editor').style.display = 'none';
            document.getElementById('item-editor-empty').style.display = 'flex';
            document.getElementById('item-guide-view').style.display = 'none';
        }

        function itemAddNew() {
            // 新增：清空 + 聚焦名称输入框 + 切到编辑器视图
            itemClearEditor();
            document.getElementById('item-editor').style.display = 'block';
            document.getElementById('item-editor-empty').style.display = 'none';
            document.getElementById('item-guide-view').style.display = 'none';
            document.getElementById('item-edit-name').focus();
        }

        function itemUpdateRarityPreview() {
            // 稀有度下拉 onChange → 刷新权重预览输入框（只读提示）
            const r = document.getElementById('item-edit-rarity').value;
            const w = (r && itemRarityWeight) ? itemRarityWeight[r] : '';
            const name = (r && itemRarityTier) ? itemRarityTier[r] : '';
            document.getElementById('item-edit-weight-preview').value =
                w ? `${w}（${name || ''}）` : '';
        }

        function itemShowGuide() {
            // 切到稀有度说明面板（说明面板已在HTML中写死内容，无需网络）
            document.getElementById('item-editor').style.display = 'none';
            document.getElementById('item-editor-empty').style.display = 'none';
            document.getElementById('item-guide-view').style.display = 'flex';
        }

        function itemHideGuide() {
            // 从说明面板返回编辑器（若当前有选中物品则保留编辑态，否则为空占位）
            document.getElementById('item-guide-view').style.display = 'none';
            if (itemCurrentName) {
                document.getElementById('item-editor').style.display = 'block';
                document.getElementById('item-editor-empty').style.display = 'none';
            } else {
                document.getElementById('item-editor').style.display = 'none';
                document.getElementById('item-editor-empty').style.display = 'flex';
            }
        }

        async function itemSave() {
            // 保存：无 original_name → 走 /items/add，否则走 /items/update（支持改名）
            const name = document.getElementById('item-edit-name').value.trim();
            if (!name) { alert('请填写物品名称'); return; }
            const subcategory = document.getElementById('item-edit-subcategory').value;
            const rarity = document.getElementById('item-edit-rarity').value;
            if (!subcategory) { alert('请选择种类（秘籍/武器/防具/暗器/丹药/坐骑）'); return; }
            if (!rarity) { alert('请选择稀有度（S/A/B/C/D）'); return; }

            const desc = document.getElementById('item-edit-description').value.trim();
            // 关键词：支持中英文逗号/空格混合，过滤空
            const rawKw = document.getElementById('item-edit-keywords').value || '';
            const kw = rawKw.split(/[,，\s]+/).map(s=>s.trim()).filter(Boolean);
            const payload = {
                name,
                subcategory,
                rarity,
                description: desc,
                linked_martial: document.getElementById('item-edit-linked-martial').value.trim(),
                source: document.getElementById('item-edit-source').value.trim(),
                owner_hint: document.getElementById('item-edit-owner-hint').value.trim(),
                note: document.getElementById('item-edit-note').value.trim(),
                keywords: kw,
            };

            const original_name = document.getElementById('item-edit-original-name').value.trim();
            let url = '/items/add';
            if (original_name) {
                payload.original_name = original_name;
                url = '/items/update';
            } else if (kw.length === 0) {
                // 新增且用户没填关键词：不传，让后端自动生成（命中更好）
                delete payload.keywords;
            }
            try {
                const res = await fetch(url, {
                    method: 'POST',
                    headers: {'Content-Type':'application/json'},
                    body: JSON.stringify(payload),
                });
                const data = await res.json();
                if (data.status === 'success') {
                    alert(data.msg || '保存成功');
                    // 保存成功后以新名作为 current（下次编辑按原名匹配）
                    itemCurrentName = name;
                    document.getElementById('item-edit-original-name').value = name;
                    itemRefreshMeta();
                    itemSearch();
                } else {
                    alert('保存失败：' + data.msg);
                }
            } catch(e) {
                alert('保存失败：' + e);
            }
        }

        async function itemDelete() {
            // 删除：按 original_name（当前加载的那一条的原名）
            const target = document.getElementById('item-edit-original-name').value.trim() || itemCurrentName;
            if (!target) { alert('请先选择要删除的物品'); return; }
            if (!confirm('确定要删除「' + target + '」吗？此操作不可撤销。')) return;
            try {
                const res = await fetch('/items/delete', {
                    method: 'POST', headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({name: target}),
                });
                const data = await res.json();
                if (data.status === 'success') {
                    alert('已删除：' + target);
                    itemClearEditor();
                    itemRefreshMeta();
                    itemSearch();
                } else {
                    alert('删除失败：' + data.msg);
                }
            } catch(e) {
                alert('删除失败：' + e);
            }
        }

        async function itemAiGenerate() {
            const descInput = document.getElementById('item-ai-desc');
            const desc = (descInput.value || '').trim();
            if (!desc) { alert('请输入物品描述词'); descInput.focus(); return; }

            // 确保编辑器可见
            document.getElementById('item-editor').style.display = 'block';
            document.getElementById('item-editor-empty').style.display = 'none';
            document.getElementById('item-guide-view').style.display = 'none';

            const btn = event ? event.target : null;
            if (btn) { btn.disabled = true; btn.textContent = '生成中...'; }

            try {
                const res = await fetch('/items/ai_generate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({desc: desc})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    const it = data.item;
                    // 拆解JSON到各个表单字段
                    document.getElementById('item-edit-name').value = it.name || '';
                    document.getElementById('item-edit-original-name').value = '';
                    document.getElementById('item-edit-rarity').value = it.rarity || 'C';
                    itemUpdateRarityPreview();
                    document.getElementById('item-edit-subcategory').value = it.subcategory || '武器';
                    document.getElementById('item-edit-source').value = it.source || '';
                    document.getElementById('item-edit-owner-hint').value = it.owner_hint || '';
                    document.getElementById('item-edit-linked-martial').value = it.linked_martial || '';
                    document.getElementById('item-edit-description').value = it.description || '';
                    document.getElementById('item-edit-keywords').value = '';
                    document.getElementById('item-edit-note').value = it.note || '';

                    itemCurrentName = null;  // 标记为新增草稿
                    alert('AI 生成完成！请审核各字段，确认无误后点「💾 保存」');
                } else {
                    alert('生成失败：' + data.message);
                }
            } catch(e) {
                alert('生成失败：' + e);
            } finally {
                if (btn) { btn.disabled = false; btn.textContent = '⚡ AI生成'; }
            }
        }

        // ======= 势力门派管理器 JavaScript =======
        let factionList = [];
        let factionCurrentName = null;

        function toggleFactionManager() {
            const modal = document.getElementById('faction-manager-modal');
            if (modal.style.display === 'none' || !modal.style.display) {
                modal.style.display = 'block';
                factionRefresh();
            } else {
                modal.style.display = 'none';
            }
        }

        async function factionRefresh() {
            try {
                const res = await fetch('/faction/list');
                const data = await res.json();
                if (data.status === 'success') {
                    factionList = data.factions || [];
                    renderFactionList();
                } else {
                    alert('加载失败：' + data.message);
                }
            } catch(e) {
                alert('网络错误：' + e);
            }
        }

        function factionSearch() {
            renderFactionList();
        }

        function renderFactionList() {
            const list = document.getElementById('faction-list');
            const count = document.getElementById('faction-count');
            const keyword = (document.getElementById('faction-search').value || '').toLowerCase();

            const filtered = keyword ? factionList.filter(f =>
                (f.name || '').toLowerCase().includes(keyword) ||
                (f.novel || '').toLowerCase().includes(keyword) ||
                (f.category || '').toLowerCase().includes(keyword) ||
                (f.location || '').toLowerCase().includes(keyword) ||
                (f.stance || '').toLowerCase().includes(keyword)
            ) : factionList;

            count.textContent = '共 ' + filtered.length + ' 项';

            if (filtered.length === 0) {
                list.innerHTML = '<div style="padding:20px; color:#555; text-align:center;">暂无门派</div>';
                return;
            }

            let html = '';
            filtered.forEach((f, idx) => {
                const isSelected = f.name === factionCurrentName;
                const catColor = (f.category || '').indexOf('正道') >= 0 ? '#8f8'
                               : (f.category || '').indexOf('邪') >= 0 ? '#f88'
                               : (f.category || '').indexOf('反清') >= 0 ? '#fa8'
                               : '#aa8';
                html += `
                    <div style="padding:10px 12px; border-bottom:1px solid #332; cursor:pointer;
                        background:${isSelected ? '#754' : 'transparent'};
                        color:${isSelected ? '#fff' : '#fc6'};"
                        onclick="factionSelect('${escapeHtml(f.name)}')">
                        <div style="font-weight:bold;">${idx + 1}. ${escapeHtml(f.name)}</div>
                        <div style="font-size:11px; color:${catColor}; margin-top:3px;">${escapeHtml(f.category || '未分类')}</div>
                        <div style="font-size:11px; color:#666; margin-top:2px;">${escapeHtml(f.novel || '')} · ${escapeHtml(f.location || '地点未知')}</div>
                    </div>
                `;
            });
            list.innerHTML = html;
        }

        async function factionSelect(name) {
            factionCurrentName = name;
            document.getElementById('faction-editor-title').textContent = '编辑门派：' + name;
            document.getElementById('faction-editor-header').style.display = 'flex';
            document.getElementById('faction-editor-empty').style.display = 'none';
            renderFactionList();

            try {
                const res = await fetch('/faction/get?name=' + encodeURIComponent(name));
                const data = await res.json();
                if (data.status === 'success') {
                    document.getElementById('faction-editor').value = JSON.stringify(data.faction, null, 2);
                } else {
                    alert('加载失败：' + data.message);
                }
            } catch(e) {
                alert('加载失败：' + e);
            }
        }

        async function factionSave() {
            let factionData;
            try {
                factionData = JSON.parse(document.getElementById('faction-editor').value);
            } catch(e) {
                alert('JSON 格式错误：' + e);
                return;
            }
            if (!factionData.name) {
                alert('JSON 缺少 name 字段');
                return;
            }
            if (!confirm('确定要保存吗？')) return;

            // factionCurrentName 为 null 时走新增（AI草稿/手动新建），否则走更新
            if (!factionCurrentName) {
                try {
                    const res = await fetch('/faction/add', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({name: factionData.name, novel: factionData.novel || '跨时代通用', category: factionData.category || '门派·正道'})
                    });
                    const data = await res.json();
                    if (data.status !== 'success') {
                        alert('新增失败：' + data.message);
                        return;
                    }
                    // 新增成功后再用 update 写入完整数据
                    const res2 = await fetch('/faction/update', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({name: factionData.name, faction: factionData})
                    });
                    const data2 = await res2.json();
                    if (data2.status === 'success') {
                        alert('保存成功！');
                        factionCurrentName = factionData.name;
                        document.getElementById('faction-editor-title').textContent = '编辑门派：' + factionData.name;
                        factionRefresh();
                    } else {
                        alert('完整数据写入失败（门派已创建）：' + data2.message);
                        factionRefresh();
                    }
                } catch(e) {
                    alert('保存失败：' + e);
                }
                return;
            }

            try {
                const res = await fetch('/faction/update', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: factionCurrentName, faction: factionData})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    alert('保存成功！');
                    // 若改名了，同步当前选中名
                    if (factionData.name && factionData.name !== factionCurrentName) {
                        factionCurrentName = factionData.name;
                    }
                    factionRefresh();
                } else {
                    alert('保存失败：' + data.message);
                }
            } catch(e) {
                alert('保存失败：' + e);
            }
        }

        async function factionDelete() {
            if (!factionCurrentName) {
                alert('请先选择一个门派');
                return;
            }
            if (!confirm('确定要删除门派「' + factionCurrentName + '」吗？此操作不可恢复！')) return;

            try {
                const res = await fetch('/faction/delete', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: factionCurrentName})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    alert('删除成功！');
                    factionCurrentName = null;
                    document.getElementById('faction-editor-header').style.display = 'none';
                    document.getElementById('faction-editor-empty').style.display = 'flex';
                    document.getElementById('faction-editor').value = '';
                    factionRefresh();
                } else {
                    alert('删除失败：' + data.message);
                }
            } catch(e) {
                alert('删除失败：' + e);
            }
        }

        function factionClearEditor() {
            if (!confirm('确定要清空编辑器吗？')) return;
            document.getElementById('faction-editor').value = '';
        }

        function factionFormatJson() {
            const ta = document.getElementById('faction-editor');
            try {
                const obj = JSON.parse(ta.value);
                ta.value = JSON.stringify(obj, null, 2);
            } catch(e) {
                alert('JSON 格式错误，无法格式化：' + e);
            }
        }

        async function factionAddNew() {
            const name = prompt('请输入门派/势力名称：');
            if (!name) return;
            const novel = prompt('请输入出典小说（可留空，默认跨时代通用）：') || '跨时代通用';
            const category = prompt('请输入类别（如：门派·正道 / 帮会·反清 / 镖局·中立）：') || '门派·正道';

            try {
                const res = await fetch('/faction/add', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: name, novel: novel, category: category})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    alert('创建成功！');
                    factionRefresh();
                    factionSelect(name);
                } else {
                    alert('创建失败：' + data.message);
                }
            } catch(e) {
                alert('创建失败：' + e);
            }
        }

        async function factionAiGenerate() {
            const descInput = document.getElementById('faction-ai-desc');
            const desc = (descInput.value || '').trim();
            if (!desc) {
                alert('请输入门派描述词');
                descInput.focus();
                return;
            }
            // 确保编辑器区域可见
            document.getElementById('faction-editor-header').style.display = 'flex';
            document.getElementById('faction-editor-empty').style.display = 'none';
            const ta = document.getElementById('faction-editor');
            ta.value = '⏳ AI 正在生成，请稍候...';
            // 按钮禁用防重复点击
            const btn = event ? event.target : null;
            if (btn) { btn.disabled = true; btn.textContent = '生成中...'; }

            try {
                const res = await fetch('/faction/ai_generate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({desc: desc})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    ta.value = JSON.stringify(data.faction, null, 2);
                    // AI 生成的内容不自动入库，factionCurrentName 保持 null（视为新建草稿）
                    factionCurrentName = null;
                    document.getElementById('faction-editor-title').textContent = 'AI生成草稿（未保存）：请审核后点「💾 保存修改」';
                    alert('AI 生成完成！请审核 JSON 内容，确认无误后点「保存修改」（将作为新门派入库）');
                } else {
                    ta.value = '';
                    alert('生成失败：' + data.message);
                }
            } catch(e) {
                ta.value = '';
                alert('生成失败：' + e);
            } finally {
                if (btn) { btn.disabled = false; btn.textContent = '⚡ AI生成'; }
            }
        }

        // ===== API 预设管理（全量可编辑）=====
        let _envSchema = null;

        function toggleApiPresets() {
            const modal = document.getElementById('api-presets-modal');
            if (modal.style.display === 'none' || !modal.style.display) {
                modal.style.display = 'block';
                loadApiPresets();
            } else {
                modal.style.display = 'none';
            }
        }

        async function loadApiPresets() {
            const body = document.getElementById('api-presets-body');
            body.innerHTML = '<p style="color:#888; font-size:12px; text-align:center;">加载中...</p>';
            try {
                const res = await fetch('/api/presets/env');
                const data = await res.json();
                if (data.status !== 'success') {
                    body.innerHTML = '<p style="color:#f88;">加载失败：' + (data.message || '未知错误') + '</p>';
                    return;
                }
                _envSchema = data.schema;
                let html = '';
                for (const group of _envSchema) {
                    html += `<div style="margin-bottom:14px; padding:12px; background:#111; border:1px solid #334; border-radius:6px;">`;
                    html += `<div style="color:#8af; font-weight:bold; margin-bottom:10px; font-size:13px; border-bottom:1px solid #223; padding-bottom:6px;">${group.label}</div>`;
                    for (const f of group.fields) {
                        const fid = 'env-' + f.key;
                        html += `<div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">`;
                        html += `<label style="width:130px; flex-shrink:0; font-size:11px; color:#889; text-align:right;">${escapeHtml(f.label)}</label>`;
                        if (f.type === 'select') {
                            html += `<select id="${fid}" style="flex:1; padding:5px 8px; background:#222; color:#0f0; border:1px solid #446; border-radius:4px; font-size:12px;">`;
                            for (const opt of (f.options || [])) {
                                html += `<option value="${opt}" ${f.value === opt ? 'selected' : ''}>${opt}</option>`;
                            }
                            html += `</select>`;
                        } else if (f.type === 'password') {
                            html += `<div style="flex:1; display:flex; gap:4px;">`;
                            html += `<input type="password" id="${fid}" value="${escapeHtml(f.value)}" data-original="${escapeHtml(f.value)}" style="flex:1; padding:5px 8px; background:#222; color:#fa8; border:1px solid #446; border-radius:4px; font-size:12px; font-family:monospace;">`;
                            html += `<button onclick="togglePwVisibility('${fid}')" style="padding:4px 8px; background:#334; color:#aac; border:1px solid #446; border-radius:3px; cursor:pointer; font-size:11px;">👁</button>`;
                            html += `</div>`;
                        } else {
                            html += `<input type="text" id="${fid}" value="${escapeHtml(f.value)}" style="flex:1; padding:5px 8px; background:#222; color:#0f0; border:1px solid #446; border-radius:4px; font-size:12px; font-family:monospace;">`;
                        }
                        html += `</div>`;
                    }
                    html += `</div>`;
                }
                html += `<div style="text-align:center; padding:10px 0;">`;
                html += `<button onclick="saveEnvConfig()" class="cmd-btn" style="background:#2a5; border-color:#4c8; color:#fff; padding:10px 30px; font-size:14px;">💾 保存所有更改</button>`;
                html += `</div>`;
                body.innerHTML = html;
            } catch(e) {
                body.innerHTML = '<p style="color:#f88;">网络错误：' + e + '</p>';
            }
        }

        function togglePwVisibility(fid) {
            const inp = document.getElementById(fid);
            if (inp.type === 'password') {
                inp.type = 'text';
            } else {
                inp.type = 'password';
            }
        }

        async function saveEnvConfig() {
            if (!_envSchema) return;
            const updates = {};
            for (const group of _envSchema) {
                for (const f of group.fields) {
                    const el = document.getElementById('env-' + f.key);
                    if (el) updates[f.key] = el.value;
                }
            }
            if (!confirm('确定要保存所有更改吗？\n\n未修改的密码字段会自动跳过。\n保存后需重启服务生效。')) return;
            try {
                const res = await fetch('/api/presets/env', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({updates: updates})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    let msg = '✅ ' + data.message;
                    if (data.skipped && data.skipped.length > 0) {
                        msg += '\n\n跳过（未修改）: ' + data.skipped.join(', ');
                    }
                    msg += '\n\n请在服务器执行：sudo systemctl restart game1';
                    alert(msg);
                    loadApiPresets();
                } else {
                    alert('❌ 保存失败：' + data.message);
                }
            } catch(e) {
                alert('❌ 网络错误：' + e);
            }
        }
