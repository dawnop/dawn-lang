cuda_tile.module @m {
  entry @softmax(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(1024), padding_value = neg_inf, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(1024), padding_value = neg_inf, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf64>, token
    %9 = reduce %7 dim=0 identities=[-Infinity : f64] : tile<1024xf64> -> tile<f64> (%10: tile<f64>, %11: tile<f64>) {
      %12 = maxf %10, %11 : tile<f64>
      yield %12 : tile<f64>
    }
    %13 = reshape %9 : tile<f64> -> tile<1xf64>
    %14 = broadcast %13 : tile<1xf64> -> tile<1024xf64>
    %15 = subf %7, %14 rounding<nearest_even> : tile<1024xf64>
    %16 = exp %15 : tile<1024xf64>
    %17 = reduce %16 dim=0 identities=[0.0 : f64] : tile<1024xf64> -> tile<f64> (%18: tile<f64>, %19: tile<f64>) {
      %20 = addf %18, %19 rounding<nearest_even> : tile<f64>
      yield %20 : tile<f64>
    }
    %21 = reshape %17 : tile<f64> -> tile<1xf64>
    %22 = broadcast %21 : tile<1xf64> -> tile<1024xf64>
    %23 = divf %16, %22 rounding<nearest_even> : tile<1024xf64>
    %24 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %25 = make_tensor_view %24, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %26 = make_partition_view %25 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %27 = store_view_tko weak %23, %26[%4] token=%8 : tile<1024xf64>, partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
