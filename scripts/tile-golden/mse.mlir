cuda_tile.module @m {
  entry @mse(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf64>, token
    %9 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %10 = make_tensor_view %9, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %11 = make_partition_view %10 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %12, %13 = load_view_tko weak %11[%4] token=%8 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf64>, token
    %14 = subf %7, %12 rounding<nearest_even> : tile<1024xf64>
    %15 = mulf %14, %14 rounding<nearest_even> : tile<1024xf64>
    %16 = reduce %15 dim=0 identities=[0.0 : f64] : tile<1024xf64> -> tile<f64> (%17: tile<f64>, %18: tile<f64>) {
      %19 = addf %17, %18 rounding<nearest_even> : tile<f64>
      yield %19 : tile<f64>
    }
    %20 = constant <f64: 1000.0> : tile<f64>
    %21 = divf %16, %20 rounding<nearest_even> : tile<f64>
    %22 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %23 = make_tensor_view %22, shape = [1], strides = [1] : tensor_view<1xf64, strides=[1]>
    %24 = make_partition_view %23 : partition_view<tile=(1), padding_value = zero, tensor_view<1xf64, strides=[1]>, dim_map=[0]>
    %25 = reshape %21 : tile<f64> -> tile<1xf64>
    %26 = broadcast %25 : tile<1xf64> -> tile<1xf64>
    %27 = store_view_tko weak %26, %24[%4] token=%13 : tile<1xf64>, partition_view<tile=(1), padding_value = zero, tensor_view<1xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
