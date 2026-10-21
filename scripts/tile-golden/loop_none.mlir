cuda_tile.module @m {
  entry @loop_none(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [128], strides = [1] : tensor_view<128xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = loop iter_values(%10 = %7) : tile<128xf64> -> (tile<128xf64>) {
      %11 = reduce %10 dim=0 identities=[-Infinity : f64] : tile<128xf64> -> tile<f64> (%12: tile<f64>, %13: tile<f64>) {
        %14 = maxf %12, %13 : tile<f64>
        yield %14 : tile<f64>
      }
      %15 = constant <f64: 1.0> : tile<f64>
      %16 = cmpf greater_than ordered %15, %11 : tile<f64> -> tile<i1>
      %17 = constant <f64: 1000.0> : tile<128xf64>
      %18 = addf %10, %17 rounding<nearest_even> : tile<128xf64>
      if %16 {
        break %10 : tile<128xf64>
      } else {
        yield
      }
      continue %18 : tile<128xf64>
    }
    %19 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %20 = make_tensor_view %19, shape = [128], strides = [1] : tensor_view<128xf64, strides=[1]>
    %21 = make_partition_view %20 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>
    %22 = store_view_tko weak %9, %21[%4] token=%0 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
