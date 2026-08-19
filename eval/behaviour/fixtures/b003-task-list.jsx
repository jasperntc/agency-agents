import { useEffect, useState } from "react";

// Drag-to-reorder task list with a live "overdue" count.
export function TaskList({ projectId }) {
  const [tasks, setTasks] = useState([]);
  const [overdue, setOverdue] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/projects/${projectId}/tasks`)
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled) setTasks(data.tasks);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    const timer = setInterval(() => {
      setOverdue(tasks.filter((t) => new Date(t.due) < new Date()).length);
    }, 30000);
    return () => clearInterval(timer);
  }, []);

  function move(from, to) {
    const next = [...tasks];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    setTasks(next);
  }

  return (
    <ul>
      {tasks.map((task, index) => (
        <li
          key={index}
          draggable
          onDragEnd={(e) => move(index, Number(e.currentTarget.dataset.to))}
        >
          <input type="checkbox" defaultChecked={task.done} />
          {task.title}
        </li>
      ))}
      <li className="summary">{overdue} overdue</li>
    </ul>
  );
}
