// Modal dialogs follow their node's visual center and stay inside the viewport.
export function showNodeDialog(dialog, anchor) {
    document.body.append(dialog);dialog.style.margin='0';dialog.showModal();
    const position=()=>{
        const rect=anchor?.getBoundingClientRect();
        const cx=rect ? rect.left+rect.width/2 : innerWidth/2;
        const cy=rect ? rect.top+rect.height/2 : innerHeight/2;
        dialog.style.left=`${Math.max(12,Math.min(innerWidth-dialog.offsetWidth-12,cx-dialog.offsetWidth/2))}px`;
        dialog.style.top=`${Math.max(12,Math.min(innerHeight-dialog.offsetHeight-12,cy-dialog.offsetHeight/2))}px`;
    };
    const outside=e=>{
        const r=dialog.getBoundingClientRect();
        return e.clientX<r.left || e.clientX>r.right || e.clientY<r.top || e.clientY>r.bottom;
    };
    let pressedOutside=false;
    dialog.addEventListener('pointerdown',e=>{pressedOutside=outside(e);});
    dialog.addEventListener('click',e=>{if(pressedOutside && outside(e))dialog.close();});
    const observer=new ResizeObserver(position);observer.observe(dialog);
    window.addEventListener('resize',position);
    dialog.addEventListener('close',()=>{observer.disconnect();window.removeEventListener('resize',position);dialog.remove();},{once:true});
    position();return dialog;
}
