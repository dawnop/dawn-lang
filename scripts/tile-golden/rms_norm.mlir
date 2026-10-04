cuda_tile.module @m {
  entry @rms_norm(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf64>, token
    %9 = mulf %7, %7 rounding<nearest_even> : tile<1024xf64>
    %10 = reduce %9 dim=0 identities=[0.0 : f64] : tile<1024xf64> -> tile<f64> (%11: tile<f64>, %12: tile<f64>) {
      %13 = addf %11, %12 rounding<nearest_even> : tile<f64>
      yield %13 : tile<f64>
    }
    %14 = constant <f64: 1000.0> : tile<f64>
    %15 = divf %10, %14 rounding<nearest_even> : tile<f64>
    %16 = constant <f64: 1.0E-5> : tile<f64>
    %17 = addf %15, %16 rounding<nearest_even> : tile<f64>
    %18 = sqrt %17 rounding<nearest_even> : tile<f64>
    %19 = reshape %18 : tile<f64> -> tile<1xf64>
    %20 = broadcast %19 : tile<1xf64> -> tile<1024xf64>
    %21 = divf %7, %20 rounding<nearest_even> : tile<1024xf64>
    %22 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %23 = make_tensor_view %22, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %24 = make_partition_view %23 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %25 = store_view_tko weak %21, %24[%4] token=%8 : tile<1024xf64>, partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
