cuda_tile.module @m {
  entry @cce_mean(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [64], strides = [1] : tensor_view<64xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(64), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(64), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<64xf64>, token
    %9 = reduce %7 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%10: tile<f64>, %11: tile<f64>) {
      %12 = addf %10, %11 rounding<nearest_even> : tile<f64>
      yield %12 : tile<f64>
    }
    %13 = constant <f64: 64.0> : tile<f64>
    %14 = divf %9, %13 rounding<nearest_even> : tile<f64>
    %15 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %16 = make_tensor_view %15, shape = [1], strides = [1] : tensor_view<1xf64, strides=[1]>
    %17 = make_partition_view %16 : partition_view<tile=(1), padding_value = zero, tensor_view<1xf64, strides=[1]>, dim_map=[0]>
    %18 = reshape %14 : tile<f64> -> tile<1xf64>
    %19 = broadcast %18 : tile<1xf64> -> tile<1xf64>
    %20 = store_view_tko weak %19, %17[%4] token=%8 : tile<1xf64>, partition_view<tile=(1), padding_value = zero, tensor_view<1xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
