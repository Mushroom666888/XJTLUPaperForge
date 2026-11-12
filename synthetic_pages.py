"""Synthetic acceptance document; contains no school materials or accounts."""

VIEWER_HTML = '''<div class="page" data-page-number="1"><canvas></canvas></div>
<div class="page" data-page-number="2"><canvas></canvas></div><script>
let current = 1, scale = 1.25;
const views = [...document.querySelectorAll('canvas')].map(canvas =>
    ({canvas, scale: 0, renderingState: 0, viewport: {width: 0, height: 0}, generation: 0}));
function render(number) {
    const view = views[number - 1];
    if (view.scale === scale && view.renderingState === 3) return;
    const token = ++view.generation;
    view.scale = scale; view.renderingState = 1;
    view.canvas.width = Math.round(160 * scale);
    view.canvas.height = Math.round(230 * scale);
    view.viewport = {width: 160 * scale, height: 230 * scale};
    setTimeout(() => {
        if (token !== view.generation) return;
        const ctx = view.canvas.getContext('2d');
        ctx.fillStyle = 'white'; ctx.fillRect(0, 0, view.canvas.width, view.canvas.height);
        ctx.fillStyle = 'black'; ctx.font = '24px Arial';
        ctx.fillText('CAN209 page ' + number, 20, 50);
        ctx.strokeStyle = number === 1 ? 'blue' : 'red';
        ctx.beginPath(); ctx.moveTo(20, 100); ctx.lineTo(200, 110 * number); ctx.stroke();
        view.renderingState = 3;
    }, 800);
}
window.PDFViewerApplication = {
    pdfDocument: {numPages: 2,
      getData: async () => new TextEncoder().encode('CAN209 synthetic source v1'),
      getPage: async () => ({getTextContent: async () => ({items:[{str:'CAN209 2023/24 FINAL'}]})})
    }, pagesCount: 2,
    get page() {return current;}, set page(n) {current = n; render(n);},
    pdfViewer: {
        get currentScale() {return scale;},
        set currentScale(n) {if (n !== scale) {scale = n; render(current);}},
        getPageView: index => views[index]
    }
}; render(1);
</script>'''
