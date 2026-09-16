import { Button, Card, Tag } from '@/components/ui';
import { SectionHead } from '@/components/layout/PageShell';
import type { ConceptQuizItem } from '../types';

/**
 * O/X 퀴즈.
 */
const CHOICE_LABEL: Record<'true' | 'false', string> = {
  true: 'O',
  false: 'X',
};

function choiceLabel(picked: boolean): string {
  return picked ? CHOICE_LABEL.true : CHOICE_LABEL.false;
}

export function ConceptQuiz({
  items,
  answers,
  onAnswer,
}: {
  items: ConceptQuizItem[];
  answers: Record<number, boolean>;
  onAnswer: (index: number, picked: boolean) => void;
}) {
  return (
    <section>
      <SectionHead title="퀴즈" />
      <div className="flex flex-col gap-3">
        {items.map((item, index) => {
          const answered = index in answers;
          const picked = answers[index];
          const correct = answered && picked === item.answer;

          return (
            <Card key={item.question}>
              <div className="flex gap-3">
                <span className="num flex-none text-sm font-semibold text-neutral-600">
                  Q{index + 1}
                </span>
                <p className="min-w-0 flex-1 text-base font-semibold">{item.question}</p>
              </div>

              <div className="flex gap-2">
                <Button
                  onClick={() => onAnswer(index, true)}
                  aria-pressed={answered && picked}
                  aria-label={`${index + 1}번 문항 O 선택`}
                >
                  O
                </Button>
                <Button
                  onClick={() => onAnswer(index, false)}
                  aria-pressed={answered && !picked}
                  aria-label={`${index + 1}번 문항 X 선택`}
                >
                  X
                </Button>
              </div>

              {answered && (
                <div className="flex flex-col gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm text-neutral-600">선택</span>
                    <Tag tone="brand">{choiceLabel(picked)}</Tag>
                    <span className="text-sm font-semibold">
                      {correct ? '맞았습니다' : `정답은 ${choiceLabel(item.answer)} 입니다`}
                    </span>
                  </div>
                  <p className="text-sm text-neutral-700">{item.explanation}</p>
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </section>
  );
}
