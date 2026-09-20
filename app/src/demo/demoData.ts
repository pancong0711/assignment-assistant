import type { KbBook, KbRow, KbKind } from '../lib/kb'
import { emptyRow } from '../lib/kb'

/** 合成示例数据（app/src/demo/，唯一允许入库的示例内容）。
 *  全部为占位合成题；学生名=学生A/学生B，班级=classA；
 *  绝不含真实题库/学生/班级信息。 */

function row(id: string, content: string, extra: Partial<KbRow> = {}): KbRow {
  return { ...emptyRow(id), content, ...extra }
}

const NOTE = '（合成示例占位题，仅演示界面，非真题）'

export const demoBooks: KbBook[] = [
  {
    kind: 'problems' as KbKind,
    chapters: [
      {
        name: 'chap01',
        rows: [
          row('P0101', '（合成示例）一质点沿 x 轴作直线运动，运动方程 x = 2t³ - 4t（SI）。求 t=2 s 时的速度与加速度。', { page: '1', type: '计算', solution: 'v = x′ = 6t²-4 → v(2)=20 m/s；a = x″ = 12t → a(2)=24 m/s²', note: NOTE }),
          row('P0102', '（合成示例）一物体自静止出发沿直线匀加速运动，前 3 s 内位移为 9 m。求其加速度与第 3 s 末的速度。', { page: '1', type: '计算', solution: 'a=2 m/s²；v=6 m/s', note: NOTE }),
          row('P0103', '（合成示例）已知某谐振动位移 x=0.05cos(4πt+π/3)（SI）。求振幅、周期与初相位。', { page: '2', type: '概念', solution: 'A=0.05 m；T=0.5 s；φ0=π/3', note: NOTE }),
        ],
      },
      {
        name: 'chap02',
        rows: [
          row('P0201', '（合成示例）理想气体等温膨胀，体积由 V₁ 增至 2V₁，求气体对外做的功（用 p₁、V₁ 表示）。', { page: '1', type: '计算', solution: 'W = p₁V₁ln2', note: NOTE }),
        ],
      },
    ],
  },
  {
    kind: 'copy' as KbKind,
    chapters: [
      {
        name: 'chap01',
        rows: [
          row('C0101', '（合成示例）抄写题干并默写动能定理表达式。', { type: '抄写', solution: 'W合 = ΔEk', note: 'copy 只查完整性' }),
        ],
      },
    ],
  },
  {
    kind: 'qa' as KbKind,
    chapters: [
      {
        name: 'chap01',
        rows: [
          row('Q0101', '（合成示例）简答：为什么匀速圆周运动是变加速运动？', { type: '简答', solution: '加速度方向时刻变化', note: NOTE }),
        ],
      },
    ],
  },
  {
    kind: 'distinguish' as KbKind,
    chapters: [
      {
        name: 'chap01',
        rows: [
          row('D0101', '（合成示例）辨析：某同学认为"合外力为零时物体一定静止"。请判断并说明理由。', { type: '辨析', solution: '错误；还可以匀速直线运动', note: '防顶替用' }),
        ],
      },
    ],
  },
  {
    kind: 'innovation' as KbKind,
    chapters: [
      {
        name: 'chap01',
        rows: [
          row('I0101', '（合成示例）开放题：设计一个用手机传感器测量重力加速度 g 的方案，说明误差来源。', { type: '开放', solution: '', note: NOTE }),
        ],
      },
    ],
  },
]
