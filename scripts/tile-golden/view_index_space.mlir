cuda_tile.module @m {
  entry @view_index_space(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = constant <i32: 1> : tile<i32>
    %3 = constant <i32: 0> : tile<i32>
    %4 = offset %arg0, %3 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %5, %6 = load_ptr_tko weak %4 token=%0 : tile<ptr<i32>> -> tile<i32>, token
    %7 = constant <i32: 1> : tile<i32>
    %8 = offset %arg0, %7 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %9, %10 = load_ptr_tko weak %8 token=%0 : tile<ptr<i32>> -> tile<i32>, token
    %11 = constant <i32: 2> : tile<i32>
    %12 = offset %arg0, %11 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<ptr<i32>> -> tile<i32>, token
    %15 = offset %arg1, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %16 = make_tensor_view %15, shape = [%5, %9], strides = [%9, %13] : tile<i32> -> tensor_view<?x?xf64, strides=[?, ?]>
    %17 = make_partition_view %16 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]>
    %18, %19 = get_index_space_shape %17 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]> -> tile<i32>
    %20, %21 = get_index_space_shape %17 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]> -> tile<i32>
    %22 = constant <f64: 0.0> : tile<16x16xf64>
    %23 = for %24 in (%1 to %18, step %2) : tile<i32> iter_values(%25 = %22) -> (tile<16x16xf64>) {
      %26 = for %27 in (%1 to %21, step %2) : tile<i32> iter_values(%28 = %25) -> (tile<16x16xf64>) {
        %29, %30 = load_view_tko weak %17[%24, %27] token=%0 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
        %31 = addf %28, %29 rounding<nearest_even> : tile<16x16xf64>
        continue %31 : tile<16x16xf64>
      }
      continue %26 : tile<16x16xf64>
    }
    %32 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %33 = make_tensor_view %32, shape = [16, 16], strides = [16, 1] : tensor_view<16x16xf64, strides=[16, 1]>
    %34 = make_partition_view %33 : partition_view<tile=(16x16), padding_value = zero, tensor_view<16x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %35, %36, %37 = get_tile_block_id : tile<i32>
    %38, %39, %40 = get_tile_block_id : tile<i32>
    %41 = store_view_tko weak %23, %34[%35, %39] token=%0 : tile<16x16xf64>, partition_view<tile=(16x16), padding_value = zero, tensor_view<16x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %42 = reshape %18 : tile<i32> -> tile<1xi32>
    %43 = broadcast %42 : tile<1xi32> -> tile<1xi32>
    %44 = assume div_by<16>, %arg3 : tile<ptr<i32>>
    %45 = make_tensor_view %44, shape = [2], strides = [1] : tensor_view<2xi32, strides=[1]>
    %46 = make_partition_view %45 : partition_view<tile=(1), padding_value = zero, tensor_view<2xi32, strides=[1]>, dim_map=[0]>
    %47 = constant <i32: 2> : tile<i32>
    %48 = muli %35, %47 : tile<i32>
    %49 = store_view_tko weak %43, %46[%48] token=%41 : tile<1xi32>, partition_view<tile=(1), padding_value = zero, tensor_view<2xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %50 = reshape %21 : tile<i32> -> tile<1xi32>
    %51 = broadcast %50 : tile<1xi32> -> tile<1xi32>
    %52 = constant <i32: 2> : tile<i32>
    %53 = muli %35, %52 : tile<i32>
    %54 = constant <i32: 1> : tile<i32>
    %55 = addi %53, %54 : tile<i32>
    %56 = store_view_tko weak %51, %46[%55] token=%49 : tile<1xi32>, partition_view<tile=(1), padding_value = zero, tensor_view<2xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
