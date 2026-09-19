<?php
// Operator-only local fixture initialization, not an Agent tool or a schema migration.
require '/var/www/html/vendor/autoload.php';
$app = require '/var/www/html/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$old = App\Models\ProductType::where('code','YOUJIE-PRD-CFG-1')->sole();
$tenant = $old->tenant_id;
$p = App\Models\ProductType::firstOrCreate(['code'=>'YOUJIE-FINALS-PRODUCT'],[
    'name'=>'有界决赛模拟装配件','description'=>'Synthetic finals fixture, not real production',
    'tenant_id'=>$tenant,'unit_of_measure'=>'件','is_active'=>true]);
$l = App\Models\Line::firstOrCreate(['code'=>'YOUJIE-FINALS-LINE'],[
    'name'=>'有界决赛测试线','description'=>'Synthetic test only, no machine controls',
    'tenant_id'=>$tenant,'is_active'=>true]);
if ($p->tenant_id != $tenant || $l->tenant_id != $tenant || !$p->is_active || !$l->is_active) {
    throw new RuntimeException('Existing finals master data conflict');
}
$l->productTypes()->syncWithoutDetaching([$p->id]);
$t=App\Models\ProcessTemplate::firstOrCreate(['product_type_id'=>$p->id,'name'=>'YOUJIE-FINALS-SIMULATED'],[
    'tenant_id'=>$tenant,'version'=>1,'is_active'=>true]);
$s=App\Models\TemplateStep::firstOrCreate(['process_template_id'=>$t->id,'step_number'=>1],[
    'name'=>'模拟装配','instruction'=>'Operator simulation only, no device action',
    'estimated_duration_minutes'=>240]);
echo json_encode(['product'=>$p->code,'line'=>$l->code,'template'=>$t->id,
    'step'=>$s->id,'provisioning'=>'local application ORM, not runtime ERP import',
    'schema_changed'=>false,'equipment_control'=>false],JSON_UNESCAPED_UNICODE).PHP_EOL;
