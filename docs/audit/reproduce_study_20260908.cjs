// Executes the actual template script with minimal DOM/network substitutes.
// Run from repository root: node docs/audit/reproduce_study_20260908.cjs
const fs = require('fs');
const vm = require('vm');
const script = fs.readFileSync('templates/study.html', 'utf8').split('<script>')[1].split('</script>')[0];
function session() {
    const elements = new Map();
    const element = id => {
        if (!elements.has(id)) {
            const classes = new Set();
            elements.set(id, {classList: {add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c)}, getAttribute: () => '', addEventListener() {}, focus() {}});
        }
        return elements.get(id);
    };
    const context = vm.createContext({
        document: {getElementById: element, querySelector: element, querySelectorAll: () => [], addEventListener() {}},
        window: {addEventListener() {}}, console, setInterval: () => 1, clearInterval() {},
        setTimeout() {}, requestAnimationFrame: fn => fn(), alert() {},
        fetch: () => Promise.resolve({ok: true, json: async () => ({})}),
    });
    vm.runInContext(script, context);
    element('complete-screen').classList.add('hidden');
    return code => vm.runInContext(code, context);
}
let failures = 0;
function check(name, actual, expected) {
    const pass = JSON.stringify(actual) === JSON.stringify(expected);
    console.log(`${pass ? 'PASS' : 'FAIL'} ${name}: actual=${JSON.stringify(actual)} expected=${JSON.stringify(expected)}`);
    if (!pass) failures++;
}
(async () => {
{
    const run = session();
    run(`activeQueue = [{id:1,reps:0,front:'a',back:'b',card_type:'recognize'}]; showNextCard();`);
    check('one card must display one remaining', run('newCountEl.textContent'), 1);
    run(`mergeCardsIntoActiveQueue([{id:2,reps:1}], [], true);`);
    run(`showAnswer(); submitReview(3);`);
    await new Promise(resolve => setImmediate(resolve));
    check('polling due card must not leave answered card queued', run('activeQueue.some(c => c.id === 1)'), false);
}
process.exitCode = failures ? 1 : 0;
})();
