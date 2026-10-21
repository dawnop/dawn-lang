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
    %15 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %16 = offset %15, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %17 = make_tensor_view %16, shape = [%5, %9], strides = [%9, %13] : tile<i32> -> tensor_view<?x?xf64, strides=[?, ?]>
    %18 = make_partition_view %17 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]>
    %19, %20 = get_index_space_shape %18 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]> -> tile<i32>
    %21, %22 = get_index_space_shape %18 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]> -> tile<i32>
    %23 = constant <f64: 0.0> : tile<16x16xf64>
    %24 = for %25 in (%1 to %19, step %2) : tile<i32> iter_values(%26 = %23) -> (tile<16x16xf64>) {
      %27 = for %28 in (%1 to %22, step %2) : tile<i32> iter_values(%29 = %26) -> (tile<16x16xf64>) {
        %30, %31 = load_view_tko weak %18[%25, %28] token=%0 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
        %32 = addf %29, %30 rounding<nearest_even> : tile<16x16xf64>
        continue %32 : tile<16x16xf64>
      }
      continue %27 : tile<16x16xf64>
    }
    %33 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %34 = make_tensor_view %33, shape = [16, 16], strides = [16, 1] : tensor_view<16x16xf64, strides=[16, 1]>
    %35 = make_partition_view %34 : partition_view<tile=(16x16), padding_value = zero, tensor_view<16x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %36, %37, %38 = get_tile_block_id : tile<i32>
    %39, %40, %41 = get_tile_block_id : tile<i32>
    %42 = store_view_tko weak %24, %35[%36, %40] token=%0 : tile<16x16xf64>, partition_view<tile=(16x16), padding_value = zero, tensor_view<16x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %43 = reshape %19 : tile<i32> -> tile<1xi32>
    %44 = broadcast %43 : tile<1xi32> -> tile<1xi32>
    %45 = assume div_by<16>, %arg3 : tile<ptr<i32>>
    %46 = make_tensor_view %45, shape = [2], strides = [1] : tensor_view<2xi32, strides=[1]>
    %47 = make_partition_view %46 : partition_view<tile=(1), padding_value = zero, tensor_view<2xi32, strides=[1]>, dim_map=[0]>
    %48 = constant <i32: 2> : tile<i32>
    %49 = muli %36, %48 : tile<i32>
    %50 = store_view_tko weak %44, %47[%49] token=%42 : tile<1xi32>, partition_view<tile=(1), padding_value = zero, tensor_view<2xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %51 = reshape %22 : tile<i32> -> tile<1xi32>
    %52 = broadcast %51 : tile<1xi32> -> tile<1xi32>
    %53 = constant <i32: 2> : tile<i32>
    %54 = muli %36, %53 : tile<i32>
    %55 = constant <i32: 1> : tile<i32>
    %56 = addi %54, %55 : tile<i32>
    %57 = store_view_tko weak %52, %47[%56] token=%50 : tile<1xi32>, partition_view<tile=(1), padding_value = zero, tensor_view<2xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
