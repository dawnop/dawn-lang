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
    %9, %10 = load_ptr_tko weak %8 token=%6 : tile<ptr<i32>> -> tile<i32>, token
    %11 = constant <i32: 2> : tile<i32>
    %12 = offset %arg0, %11 : tile<ptr<i32>>, tile<i32> -> tile<ptr<i32>>
    %13, %14 = load_ptr_tko weak %12 token=%10 : tile<ptr<i32>> -> tile<i32>, token
    %15 = offset %arg1, %1 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %16 = make_tensor_view %15, shape = [%5, %9], strides = [%9, %13] : tile<i32> -> tensor_view<?x?xf64, strides=[?, ?]>
    %17 = make_partition_view %16 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]>
    %18, %19 = get_index_space_shape %17 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]> -> tile<i32>
    %20, %21 = get_index_space_shape %17 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]> -> tile<i32>
    %22 = constant <f64: 0.0> : tile<16x16xf64>
    %23, %24 = for %25 in (%1 to %18, step %2) : tile<i32> iter_values(%26 = %22, %27 = %14) -> (tile<16x16xf64>, token) {
      %28, %29 = for %30 in (%1 to %21, step %2) : tile<i32> iter_values(%31 = %26, %32 = %27) -> (tile<16x16xf64>, token) {
        %33, %34 = load_view_tko weak %17[%25, %30] token=%32 : partition_view<tile=(16x16), padding_value = zero, tensor_view<?x?xf64, strides=[?, ?]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
        %35 = addf %31, %33 rounding<nearest_even> : tile<16x16xf64>
        continue %35, %34 : tile<16x16xf64>, token
      }
      continue %28, %29 : tile<16x16xf64>, token
    }
    %36 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %37 = broadcast %36 : tile<1x1xi32> -> tile<16x16xi32>
    %38 = iota : tile<16xi32>
    %39 = reshape %38 : tile<16xi32> -> tile<16x1xi32>
    %40 = broadcast %39 : tile<16x1xi32> -> tile<16x16xi32>
    %41 = constant <i32: 16> : tile<16x16xi32>
    %42 = muli %40, %41 : tile<16x16xi32>
    %43 = addi %37, %42 : tile<16x16xi32>
    %44 = iota : tile<16xi32>
    %45 = reshape %44 : tile<16xi32> -> tile<1x16xi32>
    %46 = broadcast %45 : tile<1x16xi32> -> tile<16x16xi32>
    %47 = addi %43, %46 : tile<16x16xi32>
    %48 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %49 = broadcast %48 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %50 = offset %49, %47 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %51 = store_ptr_tko weak %50, %23 token=%24 : tile<16x16xptr<f64>>, tile<16x16xf64> -> token
    %52 = reshape %18 : tile<i32> -> tile<1xi32>
    %53 = broadcast %52 : tile<1xi32> -> tile<1xi32>
    %54 = reshape %1 : tile<i32> -> tile<1xi32>
    %55 = broadcast %54 : tile<1xi32> -> tile<1xi32>
    %56 = iota : tile<1xi32>
    %57 = addi %55, %56 : tile<1xi32>
    %58 = reshape %arg3 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %59 = broadcast %58 : tile<1xptr<i32>> -> tile<1xptr<i32>>
    %60 = offset %59, %57 : tile<1xptr<i32>>, tile<1xi32> -> tile<1xptr<i32>>
    %61 = store_ptr_tko weak %60, %53 token=%51 : tile<1xptr<i32>>, tile<1xi32> -> token
    %62 = reshape %21 : tile<i32> -> tile<1xi32>
    %63 = broadcast %62 : tile<1xi32> -> tile<1xi32>
    %64 = reshape %2 : tile<i32> -> tile<1xi32>
    %65 = broadcast %64 : tile<1xi32> -> tile<1xi32>
    %66 = iota : tile<1xi32>
    %67 = addi %65, %66 : tile<1xi32>
    %68 = reshape %arg3 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %69 = broadcast %68 : tile<1xptr<i32>> -> tile<1xptr<i32>>
    %70 = offset %69, %67 : tile<1xptr<i32>>, tile<1xi32> -> tile<1xptr<i32>>
    %71 = store_ptr_tko weak %70, %63 token=%61 : tile<1xptr<i32>>, tile<1xi32> -> token
    return
  }
}
