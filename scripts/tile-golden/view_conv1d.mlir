cuda_tile.module @m {
  entry @view_conv1d(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = offset %arg0, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %3 = make_tensor_view %2, shape = [260], strides = [1] : tensor_view<260xf64, strides=[1]>
    %4 = make_strided_view %3 : strided_view<tile=(4), traversal_strides=[1], tensor_view<260xf64, strides=[1]>, dim_map=[0]>
    %5 = offset %arg1, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %6 = make_tensor_view %5, shape = [4], strides = [1] : tensor_view<4xf64, strides=[1]>
    %7 = make_strided_view %6 : strided_view<tile=(4), traversal_strides=[4], tensor_view<4xf64, strides=[1]>, dim_map=[0]>
    %8, %9, %10 = get_tile_block_id : tile<i32>
    %11, %12 = load_view_tko weak %4[%8] token=%0 : strided_view<tile=(4), traversal_strides=[1], tensor_view<260xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<4xf64>, token
    %13, %14 = load_view_tko weak %7[%1] token=%12 : strided_view<tile=(4), traversal_strides=[4], tensor_view<4xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<4xf64>, token
    %15 = mulf %11, %13 rounding<nearest_even> : tile<4xf64>
    %16 = reduce %15 dim=0 identities=[0.0 : f64] : tile<4xf64> -> tile<f64> (%17: tile<f64>, %18: tile<f64>) {
      %19 = addf %17, %18 rounding<nearest_even> : tile<f64>
      yield %19 : tile<f64>
    }
    %20 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %21 = make_tensor_view %20, shape = [257], strides = [1] : tensor_view<257xf64, strides=[1]>
    %22 = make_partition_view %21 : partition_view<tile=(1), padding_value = zero, tensor_view<257xf64, strides=[1]>, dim_map=[0]>
    %23, %24, %25 = get_tile_block_id : tile<i32>
    %26 = reshape %16 : tile<f64> -> tile<1xf64>
    %27 = broadcast %26 : tile<1xf64> -> tile<1xf64>
    %28 = store_view_tko weak %27, %22[%23] token=%14 : tile<1xf64>, partition_view<tile=(1), padding_value = zero, tensor_view<257xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
