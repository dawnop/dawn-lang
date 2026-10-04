cuda_tile.module @m {
  entry @grpo_adv(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [64], strides = [1] : tensor_view<64xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(8), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(8), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<8xf64>, token
    %9 = reduce %7 dim=0 identities=[0.0 : f64] : tile<8xf64> -> tile<f64> (%10: tile<f64>, %11: tile<f64>) {
      %12 = addf %10, %11 rounding<nearest_even> : tile<f64>
      yield %12 : tile<f64>
    }
    %13 = constant <f64: 8.0> : tile<f64>
    %14 = divf %9, %13 rounding<nearest_even> : tile<f64>
    %15 = reshape %14 : tile<f64> -> tile<1xf64>
    %16 = broadcast %15 : tile<1xf64> -> tile<8xf64>
    %17 = subf %7, %16 rounding<nearest_even> : tile<8xf64>
    %18 = mulf %17, %17 rounding<nearest_even> : tile<8xf64>
    %19 = reduce %18 dim=0 identities=[0.0 : f64] : tile<8xf64> -> tile<f64> (%20: tile<f64>, %21: tile<f64>) {
      %22 = addf %20, %21 rounding<nearest_even> : tile<f64>
      yield %22 : tile<f64>
    }
    %23 = divf %19, %13 rounding<nearest_even> : tile<f64>
    %24 = sqrt %23 rounding<nearest_even> : tile<f64>
    %25 = constant <f64: 1.0E-8> : tile<f64>
    %26 = addf %24, %25 rounding<nearest_even> : tile<f64>
    %27 = reshape %26 : tile<f64> -> tile<1xf64>
    %28 = broadcast %27 : tile<1xf64> -> tile<8xf64>
    %29 = divf %17, %28 rounding<nearest_even> : tile<8xf64>
    %30 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %31 = make_tensor_view %30, shape = [64], strides = [1] : tensor_view<64xf64, strides=[1]>
    %32 = make_partition_view %31 : partition_view<tile=(8), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>
    %33 = store_view_tko weak %29, %32[%4] token=%8 : tile<8xf64>, partition_view<tile=(8), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
