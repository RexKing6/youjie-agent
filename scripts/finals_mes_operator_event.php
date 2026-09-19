<?php
// Explicit local operator simulation. Not a machine event or an Agent permission.
require '/var/www/html/vendor/autoload.php';
$app=require '/var/www/html/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$run=$argv[1] ?? '';
$name=$argv[2] ?? '';
if (!preg_match('/^finals_[a-f0-9]{32}$/',$run) || !preg_match('/^MFG-WO-2026-[0-9]+$/',$name)) {
    throw new RuntimeException('Invalid test identity');
}
$wo=App\Models\WorkOrder::where('order_no',$name)->sole();
if (!str_contains($wo->description,'run='.$run.' ') || $wo->productType->code!='YOUJIE-FINALS-PRODUCT') {
    throw new RuntimeException('Not the scoped test work order');
}
if ($wo->produced_qty != 0 || $wo->planned_qty < 100) throw new RuntimeException('Unexpected initial production');
$before=['produced_qty'=>$wo->produced_qty,'status'=>$wo->status];
$wo->produced_qty=100;
$wo->status=App\Models\WorkOrder::STATUS_IN_PROGRESS;
$wo->save();
$wo->refresh();
echo json_encode(['order_no'=>$name,'run_id'=>$run,'before'=>$before,
    'after'=>['produced_qty'=>$wo->produced_qty,'status'=>$wo->status],
    'actor'=>'Codex operator under user authorized test',
    'mechanism'=>'local OpenMES application ORM, artificial production, not equipment output'],JSON_UNESCAPED_UNICODE).PHP_EOL;
