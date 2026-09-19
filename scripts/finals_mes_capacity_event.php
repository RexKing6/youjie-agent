<?php
// Human-operated test schedule, never a machine-control command.
require '/var/www/html/vendor/autoload.php';
$app=require '/var/www/html/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$run=$argv[1] ?? '';
$action=$argv[2] ?? '';
if (!preg_match('/^finals_[a-f0-9]{32}$/',$run) || !in_array($action,['create','read'])) throw new RuntimeException('Invalid scope');
$name='YOUJIE-CAP-'.substr($run,7);
$line=App\Models\Line::where('code','YOUJIE-FINALS-LINE')->sole();
$product=App\Models\ProductType::where('code','YOUJIE-FINALS-PRODUCT')->sole();
if ($action==='create') {
    if (App\Models\WorkOrder::where('order_no',$name)->exists()) throw new RuntimeException('Already exists; read only');
    App\Models\WorkOrder::create([
        'order_no'=>$name,'line_id'=>$line->id,'product_type_id'=>$product->id,
        'planned_qty'=>1,'produced_qty'=>0,'status'=>App\Models\WorkOrder::STATUS_PENDING,
        'planned_start_at'=>Carbon\Carbon::parse('2026-09-17T08:00:00+08:00')->setTimezone(config('app.timezone')),
        'planned_end_at'=>Carbon\Carbon::parse('2026-09-18T16:00:00+08:00')->setTimezone(config('app.timezone')),
        'due_date'=>'2026-09-18','description'=>'YOUJIE capacity demonstration run='.$run,
    ]);
}
$wo=App\Models\WorkOrder::where('order_no',$name)->sole();
if ($wo->line_id!=$line->id || $wo->product_type_id!=$product->id || $wo->description!=='YOUJIE capacity demonstration run='.$run) throw new RuntimeException('Scope changed');
echo json_encode(['run_id'=>$run,'order_no'=>$name,'line_code'=>$line->code,'status'=>$wo->status,
    'planned_start_at'=>$wo->planned_start_at?->toIso8601String(),
    'planned_end_at'=>$wo->planned_end_at?->toIso8601String(),
    'source'=>'OpenMES local application ORM schedule readback'],JSON_UNESCAPED_UNICODE).PHP_EOL;
